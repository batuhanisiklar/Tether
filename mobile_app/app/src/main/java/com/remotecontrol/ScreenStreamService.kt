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
import fi.iki.elonen.NanoHTTPD
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

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Uygulama task'i kapatildiginda (swipe/close) offline'a dusur.
        SignalingClient.instance?.disconnect()
        SignalingClient.instance = null
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

        if (resultCode == Activity.RESULT_OK && resultData != null) {
            startCapture(resultCode, resultData)
        } else {
            Log.e(TAG, "MediaProjection izni verilmedi veya data null")
            stopSelf()
        }

        return START_NOT_STICKY
    }

    private fun startCapture(resultCode: Int, resultData: Intent) {
        Log.i(TAG, "🎬 startCapture() çağrıldı - SignalingClient.instance = ${SignalingClient.instance != null}")
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
                    // İlk frame'de log
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

                    // Performans için yarı boyut
                    val scaledW = (width * 0.6).toInt()
                    val scaledH = (height * 0.6).toInt()
                    val scaled = Bitmap.createScaledBitmap(bmp, scaledW, scaledH, false)
                    bmp.recycle()

                    val out = ByteArrayOutputStream()
                    scaled.compress(Bitmap.CompressFormat.JPEG, 65, out)
                    scaled.recycle()

                    // Ortak byte dizisi oluştur
                    val jpegBytes = out.toByteArray()
                    // HTTP MJPEG sunucusu için hafızada tut
                    latestFrame.set(jpegBytes)
                    
                    // Frame sayacını artır
                    frameCount++
                    
                    // Aynı frame'i WebSocket üzerinden de PC'ye relay et
                    val client = SignalingClient.instance
                    if (client != null) {
                        try {
                            client.sendFrame(jpegBytes)
                            // Her 30 frame'de bir log (spam'i önlemek için)
                            if (frameCount % 30 == 0L) {
                                Log.i(TAG, "✅ Frame sent via WebSocket: ${jpegBytes.size} bytes (frame #$frameCount)")
                            }
                        } catch (e: Exception) {
                            Log.e(TAG, "❌ Frame gönderme hatası: $e", e)
                        }
                    } else {
                        // İlk 10 frame'de ve sonra her 100 frame'de bir log göster
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

            // Bildirimi güncelle
            val notifManager = getSystemService(NotificationManager::class.java)
            notifManager.notify(1, buildNotification("Ekran yayını aktif — port $PORT"))

        } catch (e: Exception) {
            Log.e(TAG, "startCapture error: $e")
            stopSelf()
        }
    }

    override fun onDestroy() {
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
 * ====================================================
 * NanoHTTPD yerine doğrudan ServerSocket kullanır.
 * Böylece response stream erken kapatılmaz ve frames
 * doğru şekilde istemciye iletilir.
 *
 * GET /stream → multipart/x-mixed-replace JPEG akışı
 * GET /        → "OK" (health check)
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
            socket.soTimeout = 0  // stream sonsuz
            val input = socket.getInputStream().bufferedReader()
            val output = socket.getOutputStream()

            // HTTP isteğini oku (path kontrolü için)
            val requestLine = input.readLine() ?: return
            // Geri kalan header'ları tüket
            while (true) {
                val line = input.readLine() ?: break
                if (line.isEmpty()) break
            }

            if (!requestLine.contains("/stream")) {
                // Health check
                val resp = "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nOK"
                output.write(resp.toByteArray())
                output.flush()
                socket.close()
                return
            }

            // MJPEG stream başlığı gönder
            val header = "HTTP/1.1 200 OK\r\n" +
                    "Content-Type: multipart/x-mixed-replace; boundary=$BOUNDARY\r\n" +
                    "Cache-Control: no-cache\r\n" +
                    "Connection: keep-alive\r\n\r\n"
            output.write(header.toByteArray())
            output.flush()

            // Frame döngüsü
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

