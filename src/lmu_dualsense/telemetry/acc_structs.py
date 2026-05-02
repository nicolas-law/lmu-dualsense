"""
ctypes mirror of the ACC shared memory physics page.

Source spec: Assetto Corsa Competizione SDK (SharedFileOut.h).
All fields are 4-byte float or int — naturally 4-byte aligned, no special pack needed.

Wheel order throughout: FL=0, FR=1, RL=2, RR=3.
"""

import ctypes


class _AccPhysics(ctypes.Structure):
    _fields_ = [
        ("packetId",                ctypes.c_int),
        ("gas",                     ctypes.c_float),   # 0.0–1.0
        ("brake",                   ctypes.c_float),   # 0.0–1.0
        ("fuel",                    ctypes.c_float),
        ("gear",                    ctypes.c_float),
        ("rpms",                    ctypes.c_float),
        ("steerAngle",              ctypes.c_float),
        ("speedKmh",                ctypes.c_float),
        ("velocity",                ctypes.c_float * 3),
        ("accG",                    ctypes.c_float * 3),
        ("wheelSlip",               ctypes.c_float * 4),   # slip ratio, 0=no slip
        ("wheelLoad",               ctypes.c_float * 4),   # deprecated
        ("wheelsPressure",          ctypes.c_float * 4),
        ("wheelAngularSpeed",       ctypes.c_float * 4),
        ("tyreWear",                ctypes.c_float * 4),   # deprecated
        ("tyreDirtyLevel",          ctypes.c_float * 4),   # deprecated
        ("tyreCoreTemperature",     ctypes.c_float * 4),
        ("camberRAD",               ctypes.c_float * 4),
        ("suspensionTravel",        ctypes.c_float * 4),
        ("drs",                     ctypes.c_float),
        ("tc",                      ctypes.c_float),
        ("heading",                 ctypes.c_float),
        ("pitch",                   ctypes.c_float),
        ("roll",                    ctypes.c_float),
        ("cgHeight",                ctypes.c_float),
        ("carDamage",               ctypes.c_float * 5),
        ("numberOfTyresOut",        ctypes.c_int),
        ("pitLimiterOn",            ctypes.c_int),
        ("abs",                     ctypes.c_float),       # ABS activation level 0–1
        ("kersCharge",              ctypes.c_float),
        ("kersInput",               ctypes.c_float),
        ("autoShifterOn",           ctypes.c_int),
        ("rideHeight",              ctypes.c_float * 2),
        ("turboBoost",              ctypes.c_float),
        ("ballast",                 ctypes.c_float),       # deprecated
        ("airDensity",              ctypes.c_float),       # deprecated
        ("airTemp",                 ctypes.c_float),
        ("roadTemp",                ctypes.c_float),
        ("localAngularVel",         ctypes.c_float * 3),
        ("finalFF",                 ctypes.c_float),
        ("performanceMeter",        ctypes.c_float),       # deprecated
        ("engineBrake",             ctypes.c_int),         # deprecated
        ("ersRecoveryLevel",        ctypes.c_int),         # deprecated
        ("ersPowerLevel",           ctypes.c_int),         # deprecated
        ("ersHeatCharging",         ctypes.c_int),         # deprecated
        ("ersIsCharging",           ctypes.c_int),         # deprecated
        ("kersCurrentKJ",           ctypes.c_float),       # deprecated
        ("drsAvailable",            ctypes.c_int),         # deprecated
        ("drsEnabled",              ctypes.c_int),         # deprecated
        ("brakeTemp",               ctypes.c_float * 4),
        ("clutch",                  ctypes.c_float),
        ("tyreTempI",               ctypes.c_float * 4),
        ("tyreTempM",               ctypes.c_float * 4),
        ("tyreTempO",               ctypes.c_float * 4),
        ("isAIControlled",          ctypes.c_int),
        ("tyreContactPoint",        ctypes.c_float * 4 * 3),
        ("tyreContactNormal",       ctypes.c_float * 4 * 3),
        ("tyreContactHeading",      ctypes.c_float * 4 * 3),
        ("brakeBias",               ctypes.c_float),
        ("localVelocity",           ctypes.c_float * 3),
        ("P2PActivations",          ctypes.c_int),         # deprecated
        ("P2PStatus",               ctypes.c_int),         # deprecated
        ("currentMaxRpm",           ctypes.c_int),
        ("mz",                      ctypes.c_float * 4),   # deprecated
        ("fx",                      ctypes.c_float * 4),   # deprecated
        ("fy",                      ctypes.c_float * 4),   # deprecated
        ("slipRatio",               ctypes.c_float * 4),
        ("slipAngle",               ctypes.c_float * 4),
        ("tcinAction",              ctypes.c_int),
        ("absInAction",             ctypes.c_int),         # 1 while ABS is cutting
        ("suspensionDamage",        ctypes.c_float * 4),   # deprecated
        ("tyreTemp",                ctypes.c_float * 4),   # deprecated
        ("waterTemp",               ctypes.c_float),
        ("brakePressure",           ctypes.c_float * 4),
        ("frontBrakeBias",          ctypes.c_int),
        ("rearLeftLongitudinalForce",  ctypes.c_float),
        ("rearRightLongitudinalForce", ctypes.c_float),
        ("frontLeftLongitudinalForce", ctypes.c_float),
        ("frontRightLongitudinalForce",ctypes.c_float),
        ("inPitLane",               ctypes.c_int),
        ("pitLimiterOn2",           ctypes.c_float),
        ("abs2",                    ctypes.c_float),
        ("autoClutch",              ctypes.c_float),
        ("rideHeight2",             ctypes.c_float),
    ]
