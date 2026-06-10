plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.remotecontrol"
    compileSdk = 34

    signingConfigs {
        create("release") {
            val storeFilePath = System.getenv("RC_RELEASE_STORE_FILE")
            val storePasswordEnv = System.getenv("RC_RELEASE_STORE_PASSWORD")
            val keyAliasEnv = System.getenv("RC_RELEASE_KEY_ALIAS")
            val keyPasswordEnv = System.getenv("RC_RELEASE_KEY_PASSWORD")

            if (
                !storeFilePath.isNullOrBlank() &&
                !storePasswordEnv.isNullOrBlank() &&
                !keyAliasEnv.isNullOrBlank() &&
                !keyPasswordEnv.isNullOrBlank()
            ) {
                storeFile = file(storeFilePath)
                storePassword = storePasswordEnv
                keyAlias = keyAliasEnv
                keyPassword = keyPasswordEnv
            } else {
                initWith(getByName("debug"))
            }
        }
    }

    defaultConfig {
        applicationId = "com.remotecontrol"
        minSdk = 26
        targetSdk = 34
        versionName = "1.0.2"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.constraintlayout)

    
    implementation(libs.camera.core)
    implementation(libs.camera.camera2)
    implementation(libs.camera.lifecycle)
    implementation(libs.camera.view)

    
    implementation(libs.okhttp)

    
    implementation(libs.coroutines.android)

    
    implementation(libs.lifecycle.service)
}
