plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android { namespace = "com.namkeen.erp"; compileSdk = 35
    defaultConfig { applicationId = "com.namkeen.erp"; minSdk = 26; targetSdk = 35; versionCode = 136; versionName = "90.bk" }
    buildTypes {
        debug { buildConfigField("String", "API_BASE_URL", "\"http://10.0.2.2:8000/\"") }
        release { isMinifyEnabled = true; buildConfigField("String", "API_BASE_URL", "\"https://erp.example.invalid/\"") }
    }
    buildFeatures { buildConfig = true }
}
