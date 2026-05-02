"""
ctypes mirrors of the rF2SharedMemoryMapPlugin binary layout.

Source spec: rF2State.h from TheIronWolfModding/rF2SharedMemoryMapPlugin, which
uses #pragma pack(push, 4).  All Structure subclasses here must carry _pack_ = 4
or field offsets will not match the game's memory and reads will return garbage.

Verified against CrewChief V4 (rF2Data.cs: [StructLayout(LayoutKind.Sequential, Pack=4)]),
the reference implementation for LMU telemetry.
"""

import ctypes

# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


class _Vec3(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("z", ctypes.c_double),
    ]


# ---------------------------------------------------------------------------
# Per-wheel telemetry
# ---------------------------------------------------------------------------


class _Wheel(ctypes.Structure):
    """rF2VehicleWheelTelemetry.  Wheel order in parent array: FL=0 FR=1 RL=2 RR=3."""

    _pack_ = 4
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
        ("mVerticalTireDeflection", ctypes.c_double),
        ("mWheelYLocation", ctypes.c_double),
        ("mToe", ctypes.c_double),
        ("mTireCarcassTemperature", ctypes.c_double),
        ("mTireInnerLayerTemperature", ctypes.c_double * 3),
        ("mExpansion", ctypes.c_uint8 * 24),
    ]


# ---------------------------------------------------------------------------
# Per-vehicle telemetry
# ---------------------------------------------------------------------------


class _VehicleTelemetry(ctypes.Structure):
    """rF2VehicleTelemetry.  Index 0 in the buffer is always the player's car."""

    _pack_ = 4
    _fields_ = [
        ("mID", ctypes.c_int),
        ("mDeltaTime", ctypes.c_double),
        ("mElapsedTime", ctypes.c_double),
        ("mLapNumber", ctypes.c_int),
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
    Full layout of the $rFactor2SMMP_Telemetry$ shared memory region.

    The plugin increments mVersionUpdateBegin before writing and
    mVersionUpdateEnd after.  Equal values mean the buffer is consistent.
    """

    _pack_ = 4
    _fields_ = [
        ("mVersionUpdateBegin", ctypes.c_uint),
        ("mVersionUpdateEnd", ctypes.c_uint),
        ("mNumVehicles", ctypes.c_int),
        ("mVehicles", _VehicleTelemetry * _MAX_VEHICLES),
    ]
