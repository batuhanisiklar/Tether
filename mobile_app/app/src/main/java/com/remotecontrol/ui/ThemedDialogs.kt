package com.remotecontrol.ui

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.view.LayoutInflater
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import androidx.annotation.DrawableRes
import androidx.appcompat.app.AlertDialog
import androidx.core.content.ContextCompat
import com.remotecontrol.R

object ThemedDialogs {
    fun showConfirmation(
        context: Context,
        title: String,
        message: String,
        positiveText: String,
        negativeText: String,
        @DrawableRes iconRes: Int = R.drawable.ic_settings,
        destructive: Boolean = false,
        onPositive: () -> Unit,
        onNegative: (() -> Unit)? = null,
    ) {
        val view = LayoutInflater.from(context).inflate(R.layout.dialog_confirm, null)
        view.findViewById<ImageView>(R.id.iv_dialog_icon).setImageResource(iconRes)
        view.findViewById<TextView>(R.id.tv_dialog_title).text = title
        view.findViewById<TextView>(R.id.tv_dialog_message).text = message

        val dialog = AlertDialog.Builder(context)
            .setView(view)
            .create()

        val positive = view.findViewById<Button>(R.id.btn_dialog_positive)
        val cancel = view.findViewById<Button>(R.id.btn_dialog_cancel)
        positive.text = positiveText
        cancel.text = negativeText

        if (destructive) {
            positive.backgroundTintList = ColorStateList.valueOf(ContextCompat.getColor(context, R.color.danger))
        }

        positive.setOnClickListener {
            dialog.dismiss()
            onPositive()
        }
        cancel.setOnClickListener {
            dialog.dismiss()
            onNegative?.invoke()
        }
        dialog.setOnCancelListener {
            onNegative?.invoke()
        }

        dialog.show()
        dialog.window?.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
    }
}
