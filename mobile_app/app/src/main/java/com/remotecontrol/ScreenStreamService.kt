package com.remotecontrol

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
import android.util.Log
import androidx.core.app.NotificationCompat
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioRecord
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicReference

/**
 * Ekran Yayın Servisi — Android 14+ uyumlu
 * ==========================================
 * MediaProjection API ile ekranı yakalar, NanoHTTPD ile
 * MJPEG olarak HTTP/8080 üzerinden yayınlar.
 *
 * Önemli: Android 14+ (API 34) startForeground() çağrısında
 * FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION gerektirir.
 */
class ScreenStreamService : Service() {

    companion object {
        private const val TAG = "ScreenStreamService"
        const val CHANNEL_ID = "screen_stream_channel"
        const val PORT = 8080
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
    }

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private var mjpegServer: MjpegServer? = null
    private val executor = Executors.newSingleThreadExecutor()
    private val latestFrame = AtomicReference<ByteArray?>(null)
    private var frameCount = 0L  // Frame sayacı (log için)

    private var audioRecord: AudioRecord? = null
    private var audioThread: Thread? = null
    @Volatile private var isAudioRecording = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Sadece yayin servisini durdur; signaling MainActivity'de kalmali
        stopSelf()
        super.onTaskRemoved(rootIntent)
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val notification = buildNotification("Ekran yayını başlatılıyor...")

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
            val pm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            mediaProjection = pm.getMediaProjection(resultCode, resultData)

            if (mediaProjection == null) {
                Log.e(TAG, "❌ MediaProjection null!")
                stopSelf()
                return
            }
            Log.i(TAG, "✅ MediaProjection oluşturuldu")

            val metrics = resources.displayMetrics
            val width = metrics.widthPixels
            val height = metrics.heightPixels
            val dpi = metrics.densityDpi

            imageReader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)

            // Android 14+ (API 34+) için MediaProjection callback kaydetmek zorunlu
            mediaProjection?.registerCallback(object : MediaProjection.Callback() {
                override fun onStop() {
                    Log.i(TAG, "MediaProjection durdu - servisi durduruyoruz")
                    stopSelf()
                }
            }, null)

            virtualDisplay = mediaProjection?.createVirtualDisplay(
                "ScreenCapture",
                width, height, dpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                imageReader?.surface,
                null, null
            )

            imageReader?.setOnImageAvailableListener({ reader ->
                val image = reader.acquireLatestImage() ?: return@setOnImageAvailableListener
                try {
                    if (frameCount == 0L) {
                        Log.i(TAG, "🎬 İlk frame yakalandı! SignalingClient.instance = ${SignalingClient.instance != null}")
                    }
                    val planes = image.planes
                    val buffer = planes[0].buffer
                    val pixelStride = planes[0].pixelStride
                    val rowStride = planes[0].rowStride
                    val rowPadding = rowStride - pixelStride * width

                    val bmp = Bitmap.createBitmap(
                        width + rowPadding / pixelStride, height, Bitmap.Config.ARGB_8888
                    )
                    bmp.copyPixelsFromBuffer(buffer)

                    // --- KALİTE GÜNCELLEMESİ YAPILAN BÖLÜM ---
                    // Görüntünün kenar sınırı 520'den 1080'e çıkarıldı.
                    val maxSide = 1080 
                    // Zorunlu küçültme oranı 0.5f'den 0.8f'e çekildi (Orijinale daha yakın).
                    val scale = minOf(0.8f, maxSide.toFloat() / maxOf(width, height))
                    val scaledW = maxOf(1, (width * scale).toInt())
                    val scaledH = maxOf(1, (height * scale).toInt())
                    
                    val scaled = Bitmap.createScaledBitmap(bmp, scaledW, scaledH, true)
                    bmp.recycle()

                    val out = ByteArrayOutputStream()
                    // Sıkıştırma kalitesi 58'den 80'e çıkarıldı (Minecraft görüntüsünü engeller).
                    scaled.compress(Bitmap.CompressFormat.JPEG, 80, out)
                    scaled.recycle()
                    // ------------------------------------------

                    val jpegBytes = out.toByteArray()
                    latestFrame.set(jpegBytes)
                    frameCount++
                    
                    val client = SignalingClient.instance
                    if (client != null) {
                        try {
                            client.sendFrame(jpegBytes)
                            if (frameCount % 30 == 0L) {
                                Log.i(TAG, "✅ Frame sent via WebSocket: ${jpegBytes.size} bytes (frame #$frameCount)")
                            }
                        } catch (e: Exception) {
                            Log.e(TAG, "❌ Frame gönderme hatası: $e", e)
                        }
                    } else {
                        if (frameCount <= 10 || frameCount % 100 == 0L) {
                            Log.w(TAG, "⚠️ SignalingClient.instance is null - frame #$frameCount gönderilemedi (${jpegBytes.size} bytes)")
                        }
                    }

                } catch (e: Exception) {
                    Log.e(TAG, "Frame error: $e")
                } finally {
                    image.close()
                }
            }, null)

            // MJPEG sunucu başlat
            mjpegServer = MjpegServer(PORT, latestFrame)
            mjpegServer?.start()
            Log.i(TAG, "Screen stream started on port $PORT")

            val notifManager = getSystemService(NotificationManager::class.java)
            notifManager.notify(1, buildNotification("Ekran yayını aktif" + if (isAudioEnabled) " (Sesli)" else ""))

            if (isAudioEnabled && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startAudioCapture()
            }

        } catch (e: Exception) {
            Log.e(TAG, "startCapture error: $e")
            stopSelf()
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
                val buffer = ByteArray(2048)
                while (isAudioRecording) {
                    val read = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                    if (read > 0) {
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

    override fun onDestroy() {
        isAudioRecording = false
        audioRecord?.stop()
        audioRecord?.release()
        audioThread?.interrupt()

        mjpegServer?.stop()
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
                "Ekran Yayını",
                NotificationManager.IMPORTANCE_LOW
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Remote Control — Ekran")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .build()
    }
}

/**
 * Basit MJPEG HTTP sunucu — Raw ServerSocket tabanlı
 */
class MjpegServer(
    private val port: Int,
    private val frameRef: AtomicReference<ByteArray?>
) {
    companion object {
        private const val TAG = "MjpegServer"
        private const val BOUNDARY = "mjpegframe"
        private const val FPS_DELAY_MS = 50L  // ~20 FPS
    }

    private var serverSocket: java.net.ServerSocket? = null
    private var serverThread: Thread? = null
    @Volatile private var running = false

    fun start() {
        running = true
        serverSocket = java.net.ServerSocket(port)
        serverThread = Thread {
            Log.i(TAG, "MJPEG server listening on port $port")
            while (running) {
                try {
                    val client = serverSocket?.accept() ?: break
                    Thread { handleClient(client) }.also { it.isDaemon = true }.start()
                } catch (e: Exception) {
                    if (running) Log.e(TAG, "Accept error: $e")
                }
            }
        }.also {
            it.isDaemon = true
            it.start()
        }
    }

    fun stop() {
        running = false
        try { serverSocket?.close() } catch (_: Exception) {}
    }

    private fun handleClient(socket: java.net.Socket) {
        try {
            socket.soTimeout = 0  
            val input = socket.getInputStream().bufferedReader()
            val output = socket.getOutputStream()

            val requestLine = input.readLine() ?: return
            while (true) {
                val line = input.readLine() ?: break
                if (line.isEmpty()) break
            }

            if (!requestLine.contains("/stream")) {
                val resp = "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nOK"
                output.write(resp.toByteArray())
                output.flush()
                socket.close()
                return
            }

            val header = "HTTP/1.1 200 OK\r\n" +
                    "Content-Type: multipart/x-mixed-replace; boundary=$BOUNDARY\r\n" +
                    "Cache-Control: no-cache\r\n" +
                    "Connection: keep-alive\r\n\r\n"
            output.write(header.toByteArray())
            output.flush()

            while (running && !socket.isClosed) {
                val jpeg = frameRef.get()
                if (jpeg != null && jpeg.isNotEmpty()) {
                    try {
                        val frameHeader = "--$BOUNDARY\r\n" +
                                "Content-Type: image/jpeg\r\n" +
                                "Content-Length: ${jpeg.size}\r\n\r\n"
                        output.write(frameHeader.toByteArray())
                        output.write(jpeg)
                        output.write("\r\n".toByteArray())
                        output.flush()
                    } catch (e: Exception) {
                        Log.d(TAG, "Client disconnected: $e")
                        break
                    }
                }
                Thread.sleep(FPS_DELAY_MS)
            }
        } catch (e: Exception) {
            Log.d(TAG, "Client error: $e")
        } finally {
            try { socket.close() } catch (_: Exception) {}
        }
    }
}