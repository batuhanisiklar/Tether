package com.remotecontrol.service

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import android.os.SystemClock
import android.util.Log
import android.view.OrientationEventListener
import android.view.Surface
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import com.remotecontrol.R
import com.remotecontrol.network.SignalingClient
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioRecord
import android.media.AudioManager
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Ekran Yayın Servisi — Android 14+ uyumlu
 * ==========================================
 * MediaProjection API ile ekrani yakalar ve
 * frameleri WebSocket uzerinden relay eder.
 *
 * Önemli: Android 14+ (API 34) startForeground() çağrısında
 * FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION gerektirir.
 *
 * Performans iyileştirmeleri:
 *   • Sabit 30 FPS frame limiter (FRAME_INTERVAL_30_FPS_MS)
 *   • Executor-tabanlı asenkron encoding (ImageReader callback'i bloklanmaz)
 *   • 720p / %65 JPEG kalitesi (bant genişliği optimizasyonu)
 *   • OrientationEventListener ile otomatik ekran döndürme algılama
 *   • VirtualDisplay yeniden oluşturma (döndürmede)
 */
class ScreenStreamService : Service() {

    companion object {
        private const val TAG = "ScreenStreamService"
        const val CHANNEL_ID = "screen_stream_channel"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        const val EXTRA_REMOTE_ROTATION_ENABLED = "remote_rotation_enabled"
        const val EXTRA_REMOTE_ROTATION_DEGREES = "remote_rotation_degrees"
        @Volatile var instance: ScreenStreamService? = null
            private set

        // ── Performans sabitleri ─────────────────────────────────────────
        private const val MAX_SIDE_HIGH = 900
        private const val MAX_SIDE_MED = 760
        private const val MAX_SIDE_LOW = 640
        private const val JPEG_QUALITY_HIGH = 72
        private const val JPEG_QUALITY_MED = 64
        private const val JPEG_QUALITY_LOW = 56
        private const val FRAME_INTERVAL_30_FPS_MS = 33L
        private const val QUEUE_BYTES_ELEVATED = 700_000L
        private const val QUEUE_BYTES_CONGESTED = 1_500_000L
        private const val QUEUE_BYTES_DROP_CAPTURE = 2_400_000L
        private const val IMAGE_READER_BUFFERS = 5      // ImageReader tampon sayısı
    }

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private val executor = Executors.newSingleThreadExecutor()
    private var frameCount = 0L  // Frame sayacı (log için)

    // ── Frame rate limiter ───────────────────────────────────────────────
    private val encodingInProgress = AtomicBoolean(false)
    private var lastFrameSentMs = 0L
    private val jpegOut = ByteArrayOutputStream(512 * 1024)
    private val frameSlotLock = Any()
    private var pendingFrame: PendingFrame? = null

    // ── Döndürme algılama ────────────────────────────────────────────────
    private var orientationListener: OrientationEventListener? = null
    private var currentRotation: Int = Surface.ROTATION_0
    @Volatile private var remoteRotationOverride: Int? = null
    private var captureWidth = 0
    private var captureHeight = 0
    private var captureDpi = 0

    // ── Ses yakalama ─────────────────────────────────────────────────────
    private var audioRecord: AudioRecord? = null
    private var audioThread: Thread? = null
    @Volatile private var isAudioRecording = false
    @Volatile private var lastMutedAudioLogMs = 0L

    // ── MediaProjection parametreleri (yeniden oluşturma için) ────────────
    private var savedResultCode: Int = Activity.RESULT_CANCELED
    private var savedResultData: Intent? = null

    private data class PendingFrame(
        val bitmap: Bitmap,
        val rotation: Int,
        val queuedBytesAtCapture: Long,
    )

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Sadece yayin servisini durdur; signaling MainActivity'de kalmali
        stopSelf()
        super.onTaskRemoved(rootIntent)
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val notification = buildNotification(getString(R.string.notification_screen_starting))

        // Android 10+ için FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION zorunlu
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(1, notification)
        }

        val resultCode = intent?.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
            ?: Activity.RESULT_CANCELED

        // API 33+ için getParcelableExtra değişti
        val resultData: Intent? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent?.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent?.getParcelableExtra(EXTRA_RESULT_DATA)
        }

        val isAudioEnabled = intent?.getBooleanExtra("EXTRA_AUDIO_ENABLED", false) ?: false
        val remoteRotationEnabled = intent?.getBooleanExtra(EXTRA_REMOTE_ROTATION_ENABLED, false) ?: false
        val remoteRotationDegrees = intent?.getIntExtra(EXTRA_REMOTE_ROTATION_DEGREES, 0) ?: 0
        remoteRotationOverride = if (remoteRotationEnabled) {
            surfaceRotationForDegrees(remoteRotationDegrees)
        } else {
            null
        }

        if (resultCode == Activity.RESULT_OK && resultData != null) {
            startCapture(resultCode, resultData, isAudioEnabled)
        } else {
            Log.e(TAG, "MediaProjection izni verilmedi veya data null")
            stopSelf()
        }

        return START_NOT_STICKY
    }

    private fun startCapture(resultCode: Int, resultData: Intent, isAudioEnabled: Boolean) {
        Log.i(TAG, "🎬 startCapture() çağrıldı - SignalingClient.instance = ${SignalingClient.instance != null}, Ses Açık: $isAudioEnabled")
        try {
            savedResultCode = resultCode
            savedResultData = resultData

            val pm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            mediaProjection = pm.getMediaProjection(resultCode, resultData)

            if (mediaProjection == null) {
                Log.e(TAG, "❌ MediaProjection null!")
                stopSelf()
                return
            }
            Log.i(TAG, "✅ MediaProjection oluşturuldu")

            // Android 14+ (API 34+) için MediaProjection callback kaydetmek zorunlu
            mediaProjection?.registerCallback(object : MediaProjection.Callback() {
                override fun onStop() {
                    Log.i(TAG, "MediaProjection durdu - servisi durduruyoruz")
                    stopSelf()
                }
            }, null)

            // Mevcut ekran boyutlarını al
            readDisplayMetrics()

            // Mevcut ekran rotasyonunu kaydet
            currentRotation = getCurrentDisplayRotation()

            // VirtualDisplay ve ImageReader oluştur
            createCaptureResources()

            // Döndürme dinleyicisini başlat
            startOrientationListener()

            // WebSocket relay aktif
            Log.i(TAG, "Screen stream started (WebSocket relay mode)")

            val notifManager = getSystemService(NotificationManager::class.java)
            notifManager.notify(
                1,
                buildNotification(
                    if (isAudioEnabled) {
                        getString(R.string.notification_screen_active_with_audio)
                    } else {
                        getString(R.string.notification_screen_active)
                    },
                ),
            )

            if (isAudioEnabled && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startAudioCapture()
            }

        } catch (e: Exception) {
            Log.e(TAG, "startCapture error: $e")
            stopSelf()
        }
    }

    // ── Ekran boyutlarını oku ────────────────────────────────────────────
    private fun readDisplayMetrics() {
        val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        captureDpi = resources.displayMetrics.densityDpi
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val bounds = wm.currentWindowMetrics.bounds
            captureWidth = bounds.width()
            captureHeight = bounds.height()
        } else {
            @Suppress("DEPRECATION")
            val metrics = android.util.DisplayMetrics()
            @Suppress("DEPRECATION")
            wm.defaultDisplay.getRealMetrics(metrics)
            captureWidth = metrics.widthPixels
            captureHeight = metrics.heightPixels
        }
    }

    // ── Mevcut ekran rotasyonunu al ─────────────────────────────────────
    private fun getCurrentDisplayRotation(): Int {
        return try {
            val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
            @Suppress("DEPRECATION")
            wm.defaultDisplay?.rotation ?: Surface.ROTATION_0
        } catch (e: Exception) {
            Log.w(TAG, "Rotasyon alınamadı (Service context): $e")
            Surface.ROTATION_0
        }
    }

    // ── VirtualDisplay + ImageReader oluştur ─────────────────────────────
    private fun createCaptureResources() {
        imageReader = ImageReader.newInstance(captureWidth, captureHeight, PixelFormat.RGBA_8888, IMAGE_READER_BUFFERS)

        virtualDisplay = mediaProjection?.createVirtualDisplay(
            "ScreenCapture",
            captureWidth, captureHeight, captureDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            imageReader?.surface,
            null, null
        )

        imageReader?.setOnImageAvailableListener({ reader ->
            val image = reader.acquireLatestImage() ?: return@setOnImageAvailableListener
            try {
                val queuedBytes = SignalingClient.instance?.pendingQueueBytes() ?: 0L
                val encodeProfile = encodeProfileForQueue(queuedBytes)
                val now = SystemClock.elapsedRealtime()

                // Kuyruk çok doluysa encode etmeden kareyi atla (CPU ve gecikme koruması).
                if (queuedBytes >= QUEUE_BYTES_DROP_CAPTURE) {
                    image.close()
                    return@setOnImageAvailableListener
                }

                // Frame rate limiter.
                if (now - lastFrameSentMs < encodeProfile.minFrameIntervalMs) {
                    image.close()
                    return@setOnImageAvailableListener
                }

                if (frameCount == 0L) {
                    Log.i(TAG, "🎬 İlk frame yakalandı! SignalingClient.instance = ${SignalingClient.instance != null}")
                }

                val planes = image.planes
                val buffer = planes[0].buffer
                val pixelStride = planes[0].pixelStride
                val rowStride = planes[0].rowStride
                val rowPadding = rowStride - pixelStride * captureWidth
                val imgWidth = captureWidth
                val imgHeight = captureHeight

                val rowWidth = imgWidth + rowPadding / pixelStride
                val rawBmp = Bitmap.createBitmap(rowWidth, imgHeight, Bitmap.Config.ARGB_8888)
                rawBmp.copyPixelsFromBuffer(buffer)
                image.close()
                val bmp = if (rowWidth == imgWidth) {
                    rawBmp
                } else {
                    val cropped = Bitmap.createBitmap(rawBmp, 0, 0, imgWidth, imgHeight)
                    rawBmp.recycle()
                    cropped
                }

                // Mevcut frame rotasyonunu yakala (closure'a al)
                val rotation = frameRotation()

                enqueueLatestFrame(bmp, rotation, queuedBytes)
            } catch (e: Exception) {
                Log.e(TAG, "Frame error: $e")
                try { image.close() } catch (_: Exception) {}
            }
        }, null)
    }

    private fun enqueueLatestFrame(bitmap: Bitmap, rotation: Int, queuedBytes: Long) {
        val previous = synchronized(frameSlotLock) {
            val replaced = pendingFrame?.bitmap
            pendingFrame = PendingFrame(
                bitmap = bitmap,
                rotation = rotation,
                queuedBytesAtCapture = queuedBytes,
            )
            replaced
        }
        previous?.recycle()

        if (encodingInProgress.compareAndSet(false, true)) {
            executor.execute { drainPendingFrames() }
        }
    }

    private fun drainPendingFrames() {
        try {
            while (true) {
                val frame = synchronized(frameSlotLock) {
                    val next = pendingFrame ?: return
                    pendingFrame = null
                    next
                }
                encodeAndSendFrame(frame)
            }
        } finally {
            encodingInProgress.set(false)
            val hasPending = synchronized(frameSlotLock) { pendingFrame != null }
            if (hasPending && encodingInProgress.compareAndSet(false, true)) {
                executor.execute { drainPendingFrames() }
            }
        }
    }

    private fun encodeAndSendFrame(frame: PendingFrame) {
        var scaled: Bitmap? = null
        try {
            val currentQueueBytes = SignalingClient.instance?.pendingQueueBytes() ?: frame.queuedBytesAtCapture
            val encodeProfile = encodeProfileForQueue(currentQueueBytes)
            val now = SystemClock.elapsedRealtime()
            val waitMs = (lastFrameSentMs + encodeProfile.minFrameIntervalMs) - now
            if (waitMs > 0L) {
                SystemClock.sleep(waitMs)
            }

            val srcW = frame.bitmap.width
            val srcH = frame.bitmap.height
            val maxSide = maxOf(srcW, srcH).coerceAtLeast(1)
            val scale = minOf(1.0f, encodeProfile.maxSide.toFloat() / maxSide.toFloat())
            val scaledW = maxOf(1, (srcW * scale).toInt())
            val scaledH = maxOf(1, (srcH * scale).toInt())

            scaled = if (scaledW == srcW && scaledH == srcH) {
                frame.bitmap
            } else {
                Bitmap.createScaledBitmap(frame.bitmap, scaledW, scaledH, false)
            }

            jpegOut.reset()
            scaled.compress(Bitmap.CompressFormat.JPEG, encodeProfile.jpegQuality, jpegOut)
            val jpegBytes = jpegOut.toByteArray()
            frameCount++
            lastFrameSentMs = SystemClock.elapsedRealtime()

            val client = SignalingClient.instance
            if (client != null) {
                client.sendFrame(jpegBytes, frame.rotation)
                if (frameCount % 120 == 0L) {
                    Log.i(
                        TAG,
                        "Frame sent: ${jpegBytes.size}B #$frameCount rot=${frame.rotation} q=$currentQueueBytes maxSide=${encodeProfile.maxSide} qlty=${encodeProfile.jpegQuality}",
                    )
                }
            } else if (frameCount <= 10 || frameCount % 100 == 0L) {
                Log.w(TAG, "⚠️ SignalingClient.instance is null - frame #$frameCount gönderilemedi (${jpegBytes.size} bytes)")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Frame encode/send error: $e", e)
        } finally {
            if (scaled != null && scaled !== frame.bitmap && !scaled.isRecycled) {
                scaled.recycle()
            }
            if (!frame.bitmap.isRecycled) {
                frame.bitmap.recycle()
            }
        }
    }

    private fun clearPendingFrame() {
        val pendingBitmap = synchronized(frameSlotLock) {
            val bmp = pendingFrame?.bitmap
            pendingFrame = null
            bmp
        }
        pendingBitmap?.recycle()
    }

    // ── Döndürme dinleyicisi ─────────────────────────────────────────────
    private fun startOrientationListener() {
        orientationListener = object : OrientationEventListener(this) {
            override fun onOrientationChanged(orientation: Int) {
                if (orientation == ORIENTATION_UNKNOWN) return
                val newRotation = getCurrentDisplayRotation()
                if (newRotation != currentRotation) {
                    Log.i(TAG, "🔄 Ekran döndü: $currentRotation → $newRotation")
                    currentRotation = newRotation
                    recreateVirtualDisplay()
                }
            }
        }
        if (orientationListener?.canDetectOrientation() == true) {
            orientationListener?.enable()
            Log.i(TAG, "✅ Döndürme dinleyicisi aktif")
        } else {
            Log.w(TAG, "⚠️ Döndürme algılanamıyor (sensör yok)")
        }
    }

    /**
     * Ekran döndüğünde VirtualDisplay ve ImageReader'ı yeniden oluşturur.
     * Yeni boyutlara uygun capture başlatılır.
     */
    private fun recreateVirtualDisplay() {
        try {
            // Eski kaynakları serbest bırak
            virtualDisplay?.release()
            virtualDisplay = null
            imageReader?.close()
            imageReader = null

            // Eski pending kareyi de at.
            encodingInProgress.set(false)
            clearPendingFrame()

            // Yeni boyutları oku
            readDisplayMetrics()

            Log.i(TAG, "🔄 VirtualDisplay yeniden oluşturuluyor: ${captureWidth}x${captureHeight} dpi=$captureDpi rot=$currentRotation")

            // Yeniden oluştur
            createCaptureResources()
        } catch (e: Exception) {
            Log.e(TAG, "recreateVirtualDisplay error: $e", e)
        }
    }

    fun refreshRotationFromRemote() {
        val newRotation = getCurrentDisplayRotation()
        if (newRotation == currentRotation) {
            return
        }
        Log.i(TAG, "Remote rotation refresh: $currentRotation -> $newRotation")
        currentRotation = newRotation
        recreateVirtualDisplay()
    }

    fun setRemoteRotationDegrees(degrees: Int) {
        remoteRotationOverride = surfaceRotationForDegrees(degrees)
        Log.i(TAG, "Remote rotation override set: ${degrees}deg -> ${remoteRotationOverride}")
    }

    private data class EncodeProfile(
        val maxSide: Int,
        val jpegQuality: Int,
        val minFrameIntervalMs: Long,
    )

    private fun encodeProfileForQueue(queuedBytes: Long): EncodeProfile {
        return when {
            queuedBytes >= QUEUE_BYTES_CONGESTED -> EncodeProfile(
                maxSide = MAX_SIDE_LOW,
                jpegQuality = JPEG_QUALITY_LOW,
                minFrameIntervalMs = FRAME_INTERVAL_30_FPS_MS,
            )
            queuedBytes >= QUEUE_BYTES_ELEVATED -> EncodeProfile(
                maxSide = MAX_SIDE_MED,
                jpegQuality = JPEG_QUALITY_MED,
                minFrameIntervalMs = FRAME_INTERVAL_30_FPS_MS,
            )
            else -> EncodeProfile(
                maxSide = MAX_SIDE_HIGH,
                jpegQuality = JPEG_QUALITY_HIGH,
                minFrameIntervalMs = FRAME_INTERVAL_30_FPS_MS,
            )
        }
    }

    private fun frameRotation(): Int {
        return remoteRotationOverride ?: currentRotation
    }

    private fun surfaceRotationForDegrees(degrees: Int): Int {
        val normalized = ((degrees % 360) + 360) % 360
        return when (((normalized + 45) / 90 * 90) % 360) {
            90 -> Surface.ROTATION_90
            180 -> Surface.ROTATION_180
            270 -> Surface.ROTATION_270
            else -> Surface.ROTATION_0
        }
    }

    private fun startAudioCapture() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q || mediaProjection == null) return
        try {
            @Suppress("NewApi")
            val audioConfig = AudioPlaybackCaptureConfiguration.Builder(mediaProjection!!)
                .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
                .addMatchingUsage(AudioAttributes.USAGE_GAME)
                .addMatchingUsage(AudioAttributes.USAGE_UNKNOWN)
                .build()

            val format = AudioFormat.Builder()
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .setSampleRate(16000)
                .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                .build()

            val minBufferSize = maxOf(
                4096, 
                AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT) * 2
            )
            
            @Suppress("NewApi")
            val builder = AudioRecord.Builder()
                .setAudioFormat(format)
                .setAudioPlaybackCaptureConfig(audioConfig)
                .setBufferSizeInBytes(minBufferSize)
            
            audioRecord = builder.build()
            audioRecord?.startRecording()
            isAudioRecording = true
            
            audioThread = Thread {
                // Daha büyük buffer: daha az paket, daha az overhead
                val buffer = ByteArray(4096)
                while (isAudioRecording) {
                    val read = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                    if (read > 0) {
                        if (!isMediaAudioEnabledForCapture()) {
                            val now = SystemClock.elapsedRealtime()
                            if (now - lastMutedAudioLogMs >= 5000L) {
                                lastMutedAudioLogMs = now
                                Log.i(TAG, "Media volume muted/zero; audio packet skipped")
                            }
                            continue
                        }
                        val client = SignalingClient.instance
                        if (client != null) {
                            val data = if (read == buffer.size) buffer else buffer.copyOf(read)
                            client.sendAudio(data)
                        }
                    }
                }
            }
            audioThread?.start()
            Log.i(TAG, "🎧 Audio capture started")
        } catch (e: Exception) {
            Log.e(TAG, "AudioCapture error", e)
        }
    }

    private fun isMediaAudioEnabledForCapture(): Boolean {
        val audioManager = getSystemService(Context.AUDIO_SERVICE) as? AudioManager ?: return true
        return try {
            val volume = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC)
            // isStreamMute OEM'e gore tutarsiz olabildigi icin stream seviyesini baz al.
            volume > 0
        } catch (_: Exception) {
            true
        }
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        isAudioRecording = false
        audioRecord?.stop()
        audioRecord?.release()
        audioThread?.interrupt()

        orientationListener?.disable()
        orientationListener = null

        clearPendingFrame()
        virtualDisplay?.release()
        imageReader?.close()
        mediaProjection?.stop()
        executor.shutdown()
        super.onDestroy()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                getString(R.string.notification_channel_screen),
                NotificationManager.IMPORTANCE_LOW
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.notification_title_screen))
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .build()
    }
}

