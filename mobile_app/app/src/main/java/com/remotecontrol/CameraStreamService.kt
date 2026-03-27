package com.remotecontrol

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.PipedInputStream
import java.io.PipedOutputStream
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicReference

/**
 * Kamera Yayın Servisi
 * =====================
 * CameraX ile arka/ön kamerayı yakalar.
 * MJPEG stream için NanoHTTPD / port 8081 kullanır.
 * ScreenStreamService /stream -> 8080, CameraStreamService /stream -> 8081
 *
 * Başlatmak için:
 *   startForegroundService(Intent(context, CameraStreamService::class.java))
 */
class CameraStreamService : LifecycleService() {

    companion object {
        private const val TAG = "CameraStreamService"
        private const val CHANNEL_ID = "camera_stream_channel"
        const val PORT = 8081
        const val EXTRA_USE_FRONT = "use_front"
    }

    private var cameraExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    private var cameraProvider: ProcessCameraProvider? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onBind(intent: Intent): IBinder? {
        super.onBind(intent)
        return null
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        val useFront = intent?.getBooleanExtra(EXTRA_USE_FRONT, false) ?: false

        // Android 10+ kamera foreground service type zorunlu
        val notification = buildNotification("Kamera yayını aktif")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(2, notification,
                android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA)
        } else {
            startForeground(2, notification)
        }

        startCamera(useFront)
        Log.i(TAG, "Camera stream service started (WebSocket relay mode)")
        return START_NOT_STICKY
    }

    private fun startCamera(useFront: Boolean) {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            cameraProvider = cameraProviderFuture.get()

            val selector = if (useFront)
                CameraSelector.DEFAULT_FRONT_CAMERA
            else
                CameraSelector.DEFAULT_BACK_CAMERA

            val analysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()

            analysis.setAnalyzer(cameraExecutor) { imageProxy ->
                processFrame(imageProxy)
            }

            try {
                cameraProvider?.unbindAll()
                cameraProvider?.bindToLifecycle(this, selector, analysis)
                Log.i(TAG, "Camera bound, front=$useFront")
            } catch (e: Exception) {
                Log.e(TAG, "Camera bind error: $e")
            }

        }, ContextCompat.getMainExecutor(this))
    }

    private fun processFrame(imageProxy: ImageProxy) {
        try {
            val yPlane = imageProxy.planes[0]
            val uPlane = imageProxy.planes[1]
            val vPlane = imageProxy.planes[2]

            val yBuffer = yPlane.buffer
            val uBuffer = uPlane.buffer
            val vBuffer = vPlane.buffer

            val ySize = yBuffer.remaining()
            val uSize = uBuffer.remaining()
            val vSize = vBuffer.remaining()

            // NV21: Y + VU sıralı
            val nv21 = ByteArray(ySize + uSize + vSize)
            yBuffer.get(nv21, 0, ySize)
            vBuffer.get(nv21, ySize, vSize)
            uBuffer.get(nv21, ySize + vSize, uSize)

            val out = java.io.ByteArrayOutputStream()
            val yuvImage = android.graphics.YuvImage(
                nv21,
                android.graphics.ImageFormat.NV21,
                imageProxy.width,
                imageProxy.height,
                null
            )
            yuvImage.compressToJpeg(
                android.graphics.Rect(0, 0, imageProxy.width, imageProxy.height),
                65,
                out
            )
            // WebSocket aracılığıyla PC'ye relay et
            SignalingClient.instance?.sendFrame(out.toByteArray())
        } catch (e: Exception) {
            Log.e(TAG, "Frame process error: $e")
        } finally {
            imageProxy.close()
        }
    }

    override fun onDestroy() {
        cameraProvider?.unbindAll()
        cameraExecutor.shutdown()
        super.onDestroy()
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Uygulama task'i kapatildiginda (swipe/close) offline'a dusur.
        SignalingClient.instance?.disconnect()
        SignalingClient.instance = null
        stopSelf()
        super.onTaskRemoved(rootIntent)
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID, "Kamera Yayını", NotificationManager.IMPORTANCE_LOW
        )
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(text: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Remote Control — Kamera")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }
}
