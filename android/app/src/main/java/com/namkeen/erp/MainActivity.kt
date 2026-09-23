package com.namkeen.erp

import android.os.Bundle
import android.widget.TextView
import android.app.Activity

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        findViewById<TextView>(R.id.api).text = "API: ${BuildConfig.API_BASE_URL}"
    }
}
