{
 "patcher": {
  "fileversion": 1,
  "appversion": {
   "major": 8,
   "minor": 6,
   "revision": 0,
   "architecture": "x64",
   "modernui": 1
  },
  "classnamespace": "box",
  "rect": [
   50.0,
   80.0,
   1420.0,
   900.0
  ],
  "bglocked": 0,
  "openinpresentation": 0,
  "default_fontsize": 12.0,
  "default_fontface": 0,
  "default_fontname": "Arial",
  "gridonopen": 1,
  "gridsize": [
   15.0,
   15.0
  ],
  "boxes": [
   {
    "box": {
     "id": "obj-1",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      30,
      10,
      900,
      22.0
     ],
     "text": "OSA MYO Controller receiver: run `osa-myo run` (OSC to 127.0.0.1:7400), control in on 7401. Change the 1 in `route /myo/1/...` for the second band."
    }
   },
   {
    "box": {
     "id": "obj-2",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      30,
      50,
      130,
      22.0
     ],
     "text": "udpreceive 7400"
    }
   },
   {
    "box": {
     "id": "obj-3",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 18,
     "patching_rect": [
      30,
      90,
      1200,
      22.0
     ],
     "text": "route /myo/1/emg/raw /myo/1/emg/rms /myo/1/emg/mav /myo/1/quat /myo/1/euler /myo/1/euler/deg /myo/1/accel /myo/1/gyro /myo/1/pose /myo/1/pose/id /myo/1/sync /myo/1/lock /myo/1/arm /myo/1/battery /myo/1/rssi /myo/1/status /myo/1/tap"
    }
   },
   {
    "box": {
     "id": "obj-4",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      30,
      150,
      220,
      22.0
     ],
     "text": "/myo/1/emg/raw  -  8 int, -128..127, 200 Hz (bundles of 4)"
    }
   },
   {
    "box": {
     "id": "obj-5",
     "maxclass": "multislider",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      30,
      175,
      220.0,
      100.0
     ],
     "size": 8,
     "setminmax": [
      -128.0,
      127.0
     ],
     "setstyle": 1
    }
   },
   {
    "box": {
     "id": "obj-6",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      260,
      150,
      220,
      22.0
     ],
     "text": "/myo/1/emg/rms  -  8 float 0..1, RMS 50 ms"
    }
   },
   {
    "box": {
     "id": "obj-7",
     "maxclass": "multislider",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      260,
      175,
      220.0,
      100.0
     ],
     "size": 8,
     "setminmax": [
      0.0,
      1.0
     ],
     "setstyle": 1
    }
   },
   {
    "box": {
     "id": "obj-8",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      490,
      150,
      220,
      22.0
     ],
     "text": "/myo/1/emg/mav  -  float 0..1, mean activity"
    }
   },
   {
    "box": {
     "id": "obj-9",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      490,
      175,
      60.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-10",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      720,
      150,
      220,
      22.0
     ],
     "text": "/myo/1/quat  -  w x y z, zero-referenced"
    }
   },
   {
    "box": {
     "id": "obj-11",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 4,
     "patching_rect": [
      720,
      175,
      110,
      22.0
     ],
     "text": "unpack 0. 0. 0. 0."
    }
   },
   {
    "box": {
     "id": "obj-12",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      720,
      210,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-13",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      775,
      210,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-14",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      830,
      210,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-15",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      885,
      210,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-16",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      950,
      150,
      220,
      22.0
     ],
     "text": "/myo/1/euler  -  roll pitch yaw (rad)"
    }
   },
   {
    "box": {
     "id": "obj-17",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 3,
     "patching_rect": [
      950,
      175,
      110,
      22.0
     ],
     "text": "unpack 0. 0. 0."
    }
   },
   {
    "box": {
     "id": "obj-18",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      950,
      210,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-19",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      1005,
      210,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-20",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      1060,
      210,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-21",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      1180,
      150,
      220,
      22.0
     ],
     "text": "/myo/1/euler/deg  -  roll pitch yaw (deg)"
    }
   },
   {
    "box": {
     "id": "obj-22",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 3,
     "patching_rect": [
      1180,
      175,
      110,
      22.0
     ],
     "text": "unpack 0. 0. 0."
    }
   },
   {
    "box": {
     "id": "obj-23",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      1180,
      210,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-24",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      1235,
      210,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-25",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      1290,
      210,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-26",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      30,
      340,
      220,
      22.0
     ],
     "text": "/myo/1/accel  -  x y z (g)"
    }
   },
   {
    "box": {
     "id": "obj-27",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 3,
     "patching_rect": [
      30,
      365,
      110,
      22.0
     ],
     "text": "unpack 0. 0. 0."
    }
   },
   {
    "box": {
     "id": "obj-28",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      30,
      400,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-29",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      85,
      400,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-30",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      140,
      400,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-31",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      260,
      340,
      220,
      22.0
     ],
     "text": "/myo/1/gyro  -  x y z (deg/s)"
    }
   },
   {
    "box": {
     "id": "obj-32",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 3,
     "patching_rect": [
      260,
      365,
      110,
      22.0
     ],
     "text": "unpack 0. 0. 0."
    }
   },
   {
    "box": {
     "id": "obj-33",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      260,
      400,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-34",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      315,
      400,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-35",
     "maxclass": "flonum",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      370,
      400,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-36",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      490,
      340,
      220,
      22.0
     ],
     "text": "/myo/1/pose  -  symbol"
    }
   },
   {
    "box": {
     "id": "obj-37",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      490,
      395,
      120,
      22.0
     ],
     "text": ""
    }
   },
   {
    "box": {
     "id": "obj-38",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      490,
      365,
      90,
      22.0
     ],
     "text": "prepend set"
    }
   },
   {
    "box": {
     "id": "obj-39",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      720,
      340,
      220,
      22.0
     ],
     "text": "/myo/1/pose/id  -  0 rest 1 fist 2 wave_in 3 wave_out 4 fingers_spread 5 double_tap 255 unknown"
    }
   },
   {
    "box": {
     "id": "obj-40",
     "maxclass": "number",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      720,
      365,
      60.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-41",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      950,
      340,
      220,
      22.0
     ],
     "text": "/myo/1/sync  -  0/1"
    }
   },
   {
    "box": {
     "id": "obj-42",
     "maxclass": "toggle",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      950,
      365,
      60.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-43",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      1180,
      340,
      220,
      22.0
     ],
     "text": "/myo/1/lock  -  0/1 (1 = locked)"
    }
   },
   {
    "box": {
     "id": "obj-44",
     "maxclass": "toggle",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      1180,
      365,
      60.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-45",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      30,
      530,
      220,
      22.0
     ],
     "text": "/myo/1/arm  -  left/right/unknown"
    }
   },
   {
    "box": {
     "id": "obj-46",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      30,
      585,
      120,
      22.0
     ],
     "text": ""
    }
   },
   {
    "box": {
     "id": "obj-47",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      30,
      555,
      90,
      22.0
     ],
     "text": "prepend set"
    }
   },
   {
    "box": {
     "id": "obj-48",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      260,
      530,
      220,
      22.0
     ],
     "text": "/myo/1/battery  -  %"
    }
   },
   {
    "box": {
     "id": "obj-49",
     "maxclass": "number",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      260,
      555,
      60.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-50",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      490,
      530,
      220,
      22.0
     ],
     "text": "/myo/1/rssi  -  dBm"
    }
   },
   {
    "box": {
     "id": "obj-51",
     "maxclass": "number",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      490,
      555,
      60.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-52",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      720,
      530,
      220,
      22.0
     ],
     "text": "/myo/1/status  -  scanning..streaming"
    }
   },
   {
    "box": {
     "id": "obj-53",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      720,
      585,
      120,
      22.0
     ],
     "text": ""
    }
   },
   {
    "box": {
     "id": "obj-54",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      720,
      555,
      90,
      22.0
     ],
     "text": "prepend set"
    }
   },
   {
    "box": {
     "id": "obj-55",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      950,
      530,
      220,
      22.0
     ],
     "text": "/myo/1/tap  -  direction count"
    }
   },
   {
    "box": {
     "id": "obj-56",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      950,
      555,
      110,
      22.0
     ],
     "text": "unpack 0 0"
    }
   },
   {
    "box": {
     "id": "obj-57",
     "maxclass": "number",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      950,
      590,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-58",
     "maxclass": "number",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      1005,
      590,
      50.0,
      22.0
     ]
    }
   },
   {
    "box": {
     "id": "obj-59",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      30,
      740,
      400,
      22.0
     ],
     "text": "control (udpsend 127.0.0.1 7401): click a message"
    }
   },
   {
    "box": {
     "id": "obj-60",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      30,
      850,
      170,
      22.0
     ],
     "text": "udpsend 127.0.0.1 7401"
    }
   },
   {
    "box": {
     "id": "obj-61",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      30,
      770,
      170,
      22.0
     ],
     "text": "/myo/1/vibrate 1"
    }
   },
   {
    "box": {
     "id": "obj-62",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      220,
      770,
      170,
      22.0
     ],
     "text": "/myo/1/vibrate 3"
    }
   },
   {
    "box": {
     "id": "obj-63",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      410,
      770,
      170,
      22.0
     ],
     "text": "/myo/1/zero"
    }
   },
   {
    "box": {
     "id": "obj-64",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      600,
      770,
      170,
      22.0
     ],
     "text": "/myo/1/lock"
    }
   },
   {
    "box": {
     "id": "obj-65",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      30,
      805,
      170,
      22.0
     ],
     "text": "/myo/1/unlock"
    }
   },
   {
    "box": {
     "id": "obj-66",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      220,
      805,
      170,
      22.0
     ],
     "text": "/myo/1/mode 2 1 1"
    }
   },
   {
    "box": {
     "id": "obj-67",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      410,
      805,
      170,
      22.0
     ],
     "text": "/myo/all/vibrate 2"
    }
   },
   {
    "box": {
     "id": "obj-68",
     "maxclass": "message",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      600,
      805,
      170,
      22.0
     ],
     "text": "/myo/1/led 0 255 255 255 0 0"
    }
   }
  ],
  "lines": [
   {
    "patchline": {
     "source": [
      "obj-2",
      0
     ],
     "destination": [
      "obj-3",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      0
     ],
     "destination": [
      "obj-5",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      1
     ],
     "destination": [
      "obj-7",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      2
     ],
     "destination": [
      "obj-9",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      3
     ],
     "destination": [
      "obj-11",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-11",
      0
     ],
     "destination": [
      "obj-12",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-11",
      1
     ],
     "destination": [
      "obj-13",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-11",
      2
     ],
     "destination": [
      "obj-14",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-11",
      3
     ],
     "destination": [
      "obj-15",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      4
     ],
     "destination": [
      "obj-17",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-17",
      0
     ],
     "destination": [
      "obj-18",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-17",
      1
     ],
     "destination": [
      "obj-19",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-17",
      2
     ],
     "destination": [
      "obj-20",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      5
     ],
     "destination": [
      "obj-22",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-22",
      0
     ],
     "destination": [
      "obj-23",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-22",
      1
     ],
     "destination": [
      "obj-24",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-22",
      2
     ],
     "destination": [
      "obj-25",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      6
     ],
     "destination": [
      "obj-27",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-27",
      0
     ],
     "destination": [
      "obj-28",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-27",
      1
     ],
     "destination": [
      "obj-29",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-27",
      2
     ],
     "destination": [
      "obj-30",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      7
     ],
     "destination": [
      "obj-32",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-32",
      0
     ],
     "destination": [
      "obj-33",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-32",
      1
     ],
     "destination": [
      "obj-34",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-32",
      2
     ],
     "destination": [
      "obj-35",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      8
     ],
     "destination": [
      "obj-38",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-38",
      0
     ],
     "destination": [
      "obj-37",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      9
     ],
     "destination": [
      "obj-40",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      10
     ],
     "destination": [
      "obj-42",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      11
     ],
     "destination": [
      "obj-44",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      12
     ],
     "destination": [
      "obj-47",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-47",
      0
     ],
     "destination": [
      "obj-46",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      13
     ],
     "destination": [
      "obj-49",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      14
     ],
     "destination": [
      "obj-51",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      15
     ],
     "destination": [
      "obj-54",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-54",
      0
     ],
     "destination": [
      "obj-53",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-3",
      16
     ],
     "destination": [
      "obj-56",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-56",
      0
     ],
     "destination": [
      "obj-57",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-56",
      1
     ],
     "destination": [
      "obj-58",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-61",
      0
     ],
     "destination": [
      "obj-60",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-62",
      0
     ],
     "destination": [
      "obj-60",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-63",
      0
     ],
     "destination": [
      "obj-60",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-64",
      0
     ],
     "destination": [
      "obj-60",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-65",
      0
     ],
     "destination": [
      "obj-60",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-66",
      0
     ],
     "destination": [
      "obj-60",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-67",
      0
     ],
     "destination": [
      "obj-60",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-68",
      0
     ],
     "destination": [
      "obj-60",
      0
     ]
    }
   }
  ],
  "dependency_cache": [],
  "autosave": 0
 }
}