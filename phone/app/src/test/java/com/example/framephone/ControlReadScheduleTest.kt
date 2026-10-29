package com.example.framephone

import com.example.framephone.bluetooth.ControlReadSchedule
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ControlReadScheduleTest {
    @Test fun slowReadsLeaveAnOutgoingTurnEvenWhenTheNextPollIsOverdue() {
        val schedule = ControlReadSchedule()
        var now = 0L
        repeat(10) {
            assertTrue(schedule.shouldRead(now))
            // A GATT read takes longer than the polling interval.
            now += 80
            schedule.completed(now, authenticated = true, standalone = true)
            now += 25 // The worker may itself be delayed past the next deadline.
            assertTrue(schedule.mustYield())
            assertFalse(schedule.shouldRead(now))
            // The worker can schedule pending marker, sensor, or pose traffic.
            schedule.outgoingTurn()
            assertTrue(schedule.shouldRead(now))
        }
    }

    @Test fun pollDelayStartsWhenReadCompletesAndResetAllowsImmediatePoll() {
        val schedule = ControlReadSchedule()
        schedule.completed(100, authenticated = true, standalone = true)
        schedule.outgoingTurn()
        assertFalse(schedule.shouldRead(119))
        assertTrue(schedule.shouldRead(120))
        schedule.reset()
        assertTrue(schedule.shouldRead(0))
    }
}
