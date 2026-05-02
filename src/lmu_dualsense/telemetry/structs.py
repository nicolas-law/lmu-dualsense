"""
ctypes mirrors of the rF2SharedMemoryMapPlugin binary layout.

Source spec: rF2 InternalsPlugin SDK, MSVC default alignment (no packing pragma).
ctypes natural alignment matches MSVC on x86-64, so no _pack_ override is needed.
Comment annotations show the padding bytes ctypes inserts automatically.
"""

import ctypes

# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


class _Vec3(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("z", ctypes.c_double),
    ]


# ---------------------------------------------------------------------------
# Per-wheel telemetry  (sizeof ≈ 376 bytes)
# ---------------------------------------------------------------------------


class _Wheel(ctypes.Structure):
    """rF2VehicleWheelTelemetry.  Wheel order in parent array: FL=0 FR=1 RL=2 RR=3."""

    _fields_ = [
        ("mSuspensionDeflection", ctypes.c_double),
        ("mRideHeight", ctypes.c_double),
        ("mSuspForce", ctypes.c_double),
        ("mBrakeTemp", ctypes.c_double),
        ("mBrakePressure", ctypes.c_double),
        ("mRotation", ctypes.c_double),           # rad/s, positive = forward
        ("mLateralPatchVel", _Vec3),
        ("mLongitudinalPatchVel", _Vec3),
        ("mLateralGroundVel", _Vec3),
        ("mLongitudinalGroundVel", _Vec3),
        ("mCamber", ctypes.c_double),
        ("mLateralForce", _Vec3),
        ("mLongitudinalForce", _Vec3),
        ("mTireLoad", _Vec3),
        ("mGripFract", ctypes.c_double),          # 0 = full grip, ~1 = full slide
        ("mPressure", ctypes.c_double),
        ("mTemperature", ctypes.c_double * 3),
        ("mWear", ctypes.c_double),
        ("mTerrainName", ctypes.c_char * 16),
        ("mSurfaceType", ctypes.c_uint8),
        ("mFlat", ctypes.c_uint8),
        ("mDetached", ctypes.c_uint8),
        ("mStaticUndeflectedRadius", ctypes.c_uint8),
        # ← 4 bytes alignment padding inserted by ctypes (next field is double)
        ("mVerticalTireDeflection", ctypes.c_double),
        ("mWheelYLocation", ctypes.c_double),
        ("mToe", ctypes.c_double),
        ("mTireCarcassTemperature", ctypes.c_double),
        ("mTireInnerLayerTemperature", ctypes.c_double * 3),
        ("mExpansion", ctypes.c_uint8 * 24),
    ]


# ---------------------------------------------------------------------------
# Per-vehicle telemetry  (sizeof ≈ 2176 bytes)
# ---------------------------------------------------------------------------


class _VehicleTelemetry(ctypes.Structure):
    """rF2VehicleTelemetry.  Index 0 in the buffer is always the player's car."""

    _fields_ = [
        ("mID", ctypes.c_int),
        # ← 4 bytes padding (next field is double)
        ("mDeltaTime", ctypes.c_double),
        ("mElapsedTime", ctypes.c_double),
        ("mLapNumber", ctypes.c_int),
        # ← 4 bytes padding
        ("mLapStartET", ctypes.c_double),
        ("mVehicleName", ctypes.c_char * 64),
        ("mTrackName", ctypes.c_char * 64),
        ("mPos", _Vec3),
        ("mLocalVel", _Vec3),                     # m/s in vehicle-local axes
        ("mLocalAccel", _Vec3),
        ("mOri", _Vec3 * 3),                      # 3×3 orientation matrix (row-major)
        ("mLocalRot", _Vec3),
        ("mLocalRotAccel", _Vec3),
        ("mGear", ctypes.c_int),                  # -1=reverse  0=neutral  1+=forward
        # ← 4 bytes padding
        ("mEngineRPM", ctypes.c_double),
        ("mEngineWaterTemp", ctypes.c_double),
        ("mEngineOilTemp", ctypes.c_double),
        ("mClutchRPM", ctypes.c_double),
        ("mUnfilteredThrottle", ctypes.c_double),
        ("mUnfilteredBrake", ctypes.c_double),
        ("mUnfilteredSteering", ctypes.c_double),
        ("mUnfilteredClutch", ctypes.c_double),
        ("mFilteredThrottle", ctypes.c_double),
        ("mFilteredBrake", ctypes.c_double),
        ("mFilteredSteering", ctypes.c_double),
        ("mFilteredClutch", ctypes.c_double),
        ("mSteeringShaftTorque", ctypes.c_double),
        ("mFront3rdDeflection", ctypes.c_double),
        ("mRear3rdDeflection", ctypes.c_double),
        ("mFrontWingHeight", ctypes.c_double),
        ("mFrontRideHeight", ctypes.c_double),
        ("mRearRideHeight", ctypes.c_double),
        ("mDrag", ctypes.c_double),
        ("mFrontDownforce", ctypes.c_double),
        ("mRearDownforce", ctypes.c_double),
        ("mFuel", ctypes.c_double),
        ("mEngineMaxRPM", ctypes.c_double),
        ("mScheduledStops", ctypes.c_uint8),
        ("mOverheating", ctypes.c_uint8),
        ("mDetached", ctypes.c_uint8),
        ("mHeadlights", ctypes.c_uint8),
        ("mDentSeverity", ctypes.c_uint8 * 8),
        # ← 4 bytes padding (offset 564 → 568 for double alignment)
        ("mLastImpactET", ctypes.c_double),
        ("mLastImpactMagnitude", ctypes.c_double),
        ("mLastImpactPos", _Vec3),
        ("mExpansion", ctypes.c_uint8 * 64),
        ("mWheels", _Wheel * 4),
    ]


# ---------------------------------------------------------------------------
# Shared memory buffer header + vehicle array
# ---------------------------------------------------------------------------

_MAX_VEHICLES = 128


class _TelemetryBuffer(ctypes.Structure):
    """
    Full layout of the $rF2SMMP_Telemetry$ shared memory region.

    mCurrentRead is incremented on each write; odd value means a write is in
    progress.  For haptic feedback we tolerate the rare torn read and skip the
    consistency check.
    """

    _fields_ = [
        ("mCurrentRead", ctypes.c_uint),
        ("mBytesUpdatedHint", ctypes.c_int),
        ("mNumVehicles", ctypes.c_int),
        # ← 4 bytes padding (_VehicleTelemetry array is double-aligned)
        ("mVehicles", _VehicleTelemetry * _MAX_VEHICLES),
    ]
