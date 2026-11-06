package com.example.framephone

import com.example.framephone.video.CapturePrompt
import org.junit.Assert.*
import org.junit.Test

class CapturePromptTest {
    @Test fun blockedBackgroundLaunchKeepsForegroundAndManualRecovery() {
        val prompt = CapturePrompt()
        assertTrue(prompt.request(0, foreground = false))
        assertFalse(prompt.handled) // A launch request is not proof Android showed it.
        assertFalse(prompt.request(500, foreground = true))
        assertFalse(prompt.request(4000, foreground = false))
        assertTrue(prompt.request(4000, foreground = true))
        assertFalse(prompt.request(8000, foreground = true))
        assertTrue(prompt.request(8000, foreground = true, manual = true))
    }

    @Test fun denialSuppressesAutomaticPromptsUntilUnlockButAllowsManualRetry() {
        val prompt = CapturePrompt()
        prompt.shown()
        assertFalse(prompt.request(4000, foreground = true, manual = true))
        prompt.finished()
        assertFalse(prompt.request(4000, foreground = false))
        assertFalse(prompt.request(4000, foreground = true))
        assertTrue(prompt.request(4000, foreground = true, manual = true))
        prompt.shown()
        prompt.finished()
        prompt.unlocked()
        assertTrue(prompt.request(5000, foreground = false))
    }

    @Test fun unlockDoesNotDuplicateAnOpenDialog() {
        val prompt = CapturePrompt()
        prompt.shown()
        prompt.unlocked()
        assertFalse(prompt.request(4000, foreground = false))
        prompt.finished()
        assertTrue(prompt.request(4000, foreground = false))
        prompt.suppress()
        assertFalse(prompt.request(8000, foreground = true))
    }
}
