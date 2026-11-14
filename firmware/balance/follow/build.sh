#!/bin/sh
# Builds ./follow with an embedded Info.plist (needed to see the iPhone's Continuity Camera).
cd "$(dirname "$0")" && swiftc -O follow.swift -o follow -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker Info.plist
