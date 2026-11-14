// Person-following for the balancing robot. HackPrinceton, Nov 14 2026.
//
// iPhone on the mast (Continuity Camera) -> Apple Vision person detection -> speed and turn
// -> POST to drive.py (http://127.0.0.1:8765/auto) -> robot over USB.
// drive.py only passes these on while Follow is switched ON on the drive page (F); held keys override; X stops.
//
// Build:  ./build.sh      Run (in macOS Terminal, so it can ask for camera access):
//   ./follow --dry            detect only, never drives (prints what it sees, saves follow_view.jpg every second)
//   ./follow --turn-only      balance in place, only turn to face the person (safe first test)
//   ./follow --yellow ...     follow something bright YELLOW instead of a person (ball, sticky note); combine with
//                             --dry / --turn-only. --distance is then the patch size to hold (default 0.35; bigger =
//                             stay closer), --speed the top follow speed (default 0.4 m/s)
//   ./follow                  follow (still needs Follow ON on the drive page)
// Options: --camera-back   the phone's camera faces the robot's back (Wago side): drive backward toward the person
//          --rotate left|right   if people show up sideways in follow_view.jpg
//          --distance 0.45  upper-body width as a fraction of the picture to hold (bigger = stay closer; 0.33 ~1.3 m)
// The camera is only ~40 cm off the floor, so whole bodies don't fit until ~4 m away: it tracks the upper body
// and judges distance by its WIDTH (shoulders fit in frame from ~0.7 m).
import AVFoundation
import AppKit
import CoreImage
import Vision

let args = CommandLine.arguments
func opt(_ name: String) -> String? { if let i = args.firstIndex(of: name), i + 1 < args.count { return args[i + 1] }; return nil }
let dry = args.contains("--dry")
let cameraBack = args.contains("--camera-back")
let targetW = Double(opt("--distance") ?? "0.45") ?? 0.45   // person: upper-body width to hold (bigger = closer). 0.33 felt too far
let turnOnly = args.contains("--turn-only")
let yellowMode = args.contains("--yellow")
let targetY = Double(opt("--distance") ?? "0.35") ?? 0.35   // yellow patch size to hold: bigger = stops closer (0.12 and 0.28 stayed too far)
let followVmax = Double(opt("--speed") ?? "0.4") ?? 0.4      // m/s cap while following yellow
let rotation: CGImagePropertyOrientation = {
    switch opt("--rotate") { case "left": return .left; case "right": return .right; default: return .up }
}()
let snapPath = (FileManager.default.currentDirectoryPath as NSString).appendingPathComponent("follow_view.jpg")

// Controller tuning (gentle on purpose: the video arrives ~0.2 s late)
let KW = 2.0        // rad/s per unit of horizontal offset (person at the picture edge = 1 rad/s)
let KV = 1.2        // m/s per unit of width error
let VMAX = 0.25, VBACK = -0.10, WMAX = 1.0
let DEAD_X = 0.06, DEAD_W = 0.03
let TOO_CLOSE_W = max(0.55, targetW + 0.15)   // much closer than wanted: back off
let LOST_AFTER = 0.5  // s without a person -> stop

final class Follower: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    let session = AVCaptureSession()
    let queue = DispatchQueue(label: "camera")
    let ciContext = CIContext()
    var v = 0.0, w = 0.0
    var lastSeen = Date.distantPast, lastSnap = Date.distantPast, lastPrint = Date.distantPast
    var frames = 0, printedSize = false

    func start(tries: Int = 0) {
        let found = AVCaptureDevice.DiscoverySession(deviceTypes: [.continuityCamera, .external],
                                                     mediaType: .video, position: .unspecified).devices
        guard let dev = found.first(where: { $0.deviceType == .continuityCamera }) ?? found.first else {
            // the iPhone often shows up a few seconds after the first look, so keep looking (without blocking the run loop)
            if tries == 0 { print("Looking for the iPhone camera (up to 20 s). Lock the iPhone, keep it near the Mac, Wi-Fi and Bluetooth on...") }
            if tries < 40 { DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.start(tries: tries + 1) }; return }
            print("No iPhone camera found. Open FaceTime, pick the iPhone under Video, quit FaceTime, then run this again."); exit(1)
        }
        print("Target: \(yellowMode ? "something bright YELLOW" : "a person (upper body)")")
        print("Camera: \(dev.localizedName)\(dry ? "   (DRY RUN: detection only, no driving)" : (turnOnly ? "   (TURN ONLY: no forward/back)" : ""))")
        do {
            session.beginConfiguration()
            if session.canSetSessionPreset(.vga640x480) { session.sessionPreset = .vga640x480 }
            let input = try AVCaptureDeviceInput(device: dev)
            guard session.canAddInput(input) else { print("Can't use that camera."); exit(1) }
            session.addInput(input)
            let out = AVCaptureVideoDataOutput()
            out.alwaysDiscardsLateVideoFrames = true
            out.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
            out.setSampleBufferDelegate(self, queue: queue)
            session.addOutput(out)
            session.commitConfiguration()
            session.startRunning()
        } catch { print("Camera error: \(error)"); exit(1) }
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sb: CMSampleBuffer, from connection: AVCaptureConnection) {
        frames += 1
        if frames % 2 != 0 { return }                       // ~15 detections per second is plenty
        guard let pb = CMSampleBufferGetImageBuffer(sb) else { return }
        if !printedSize { printedSize = true; print("Frames: \(CVPixelBufferGetWidth(pb))x\(CVPixelBufferGetHeight(pb))") }

        if yellowMode { followYellow(pb); return }
        let req = VNDetectHumanRectanglesRequest()
        req.upperBodyOnly = true
        try? VNImageRequestHandler(cvPixelBuffer: pb, orientation: rotation).perform([req])
        let people = (req.results ?? []).filter { $0.confidence > 0.35 }         // 0.5 dropped people near the edge or mid-turn
        let best = choosePerson(people)                                           // locked person, or the closest one

        var cx = 0.5, h = 0.0
        if let b = best {
            lastSeen = Date()
            cx = Double(b.boundingBox.midX); h = Double(b.boundingBox.width)
            let ex = cx - 0.5, eh = targetW - h
            lastEx = ex
            var wCmd = abs(ex) < DEAD_X ? 0 : -KW * ex                   // person on the right -> turn right (w < 0)
            var vCmd = abs(eh) < DEAD_W ? 0 : KV * eh                    // narrow in the picture -> drive closer
            if h > TOO_CLOSE_W { vCmd = VBACK }                           // much too close -> back off
            if turnOnly { vCmd = 0 }
            vCmd = max(VBACK, min(VMAX, vCmd)); wCmd = max(-WMAX, min(WMAX, wCmd))
            if cameraBack { vCmd = -vCmd }
            v = 0.6 * v + 0.4 * vCmd; w = 0.6 * w + 0.4 * wCmd
        } else {
            let lost = Date().timeIntervalSince(lastSeen)
            v = 0.6 * v; if lost > LOST_AFTER { v = 0 }                    // can't see them: no driving forward or back
            if lost > SEARCH_FOR { w = 0 }                                 // gave up: hold still
            else if abs(lastEx) > 0.15 { w = 0.6 * w + 0.4 * (lastEx > 0 ? -SEARCH_W : SEARCH_W) }   // left near the edge: keep turning that way
            else if lost > LOST_AFTER { w = 0 }
        }
        if !dry { post(v: v, w: w, found: best != nil, cx: cx, h: h) }

        let now = Date()
        if now.timeIntervalSince(lastPrint) > 0.5 {
            lastPrint = now
            if let _ = best { print(String(format: "person: offset %+.2f  size %.2f  [%@]  ->  speed %+.2f m/s  turn %+.2f rad/s", cx - 0.5, h, lockNote, v, w)) }
            else { print(people.isEmpty ? "no person in view" : "no target (\(people.count) other person(s) in view, ignored)") }
        }
        if now.timeIntervalSince(lastSnap) > 1.0 { lastSnap = now; snapshot(pb, people: people, best: best) }
    }

    // ---- person lock: stay on one person in a crowd (nearest to where they were, similar size); re-pick the
    //      closest (widest) person only after the locked one has been out of sight for P_HOLD seconds
    var pTrack = CGRect.zero, pLast = Date.distantPast, lockNote = "", lastEx = 0.0
    let SEARCH_FOR = 2.0, SEARCH_W = 0.5     // lost near the picture edge: keep turning that way at 0.5 rad/s for up to 2 s
    let P_GATE = 0.25, P_HOLD = 1.0
    func choosePerson(_ people: [VNHumanObservation]) -> VNHumanObservation? {
        let now = Date()
        if now.timeIntervalSince(pLast) < P_HOLD && pTrack.width > 0 {
            var best: (Double, VNHumanObservation)? = nil
            for p in people {
                let b = p.boundingBox
                let d = hypot(Double(b.midX - pTrack.midX), Double(b.midY - pTrack.midY))
                let r = Double(b.width / pTrack.width)
                if d > P_GATE || r < 0.6 || r > 1.6 { continue }
                let score = d + 0.3 * abs(log(r))
                if best == nil || score < best!.0 { best = (score, p) }
            }
            guard let p = best?.1 else { return nil }                       // locked person hidden: hold, don't switch
            pTrack = p.boundingBox; pLast = now
            lockNote = people.count > 1 ? "locked, ignoring \(people.count - 1) other" : "locked"
            return p
        }
        guard let p = people.max(by: { $0.boundingBox.width < $1.boundingBox.width }) else { return nil }
        pTrack = p.boundingBox; pLast = now; lockNote = "acquired"
        return p
    }

    // ---- yellow target: blobs + track lock, so another yellow thing entering the frame can't steal the target
    struct Blob { var n = 0; var sx = 0.0; var sy = 0.0; var minX = Int.max; var maxX = 0; var minY = Int.max; var maxY = 0 }
    var mask = [UInt8]()
    var trackCx = 0.5, trackCy = 0.5, trackS = 0.0, trackLast = Date.distantPast
    var lastBlobs: [CGRect] = [], yellowBox = CGRect.zero
    let STEP = 8, GATE = 0.22, LOCK_HOLD = 0.7
    let ACQ_MIN = 0.045, KEEP_MIN = 0.025   // don't pick up tiny far-away yellow specks; drop a target that shrinks to nothing

    func yellowBlobs(_ pb: CVPixelBuffer) -> (blobs: [Blob], total: Int, gw: Int, gh: Int) {
        CVPixelBufferLockBaseAddress(pb, .readOnly); defer { CVPixelBufferUnlockBaseAddress(pb, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(pb) else { return ([], 1, 1, 1) }
        let W = CVPixelBufferGetWidth(pb), H = CVPixelBufferGetHeight(pb), bpr = CVPixelBufferGetBytesPerRow(pb)
        let gw = W / STEP, gh = H / STEP
        if mask.count != gw * gh { mask = [UInt8](repeating: 0, count: gw * gh) }
        let p = base.assumingMemoryBound(to: UInt8.self)
        for gy in 0..<gh {
            let row = p + gy * STEP * bpr
            for gx in 0..<gw {
                let px = row + gx * STEP * 4
                let b = Float(px[0]) / 255, g = Float(px[1]) / 255, r = Float(px[2]) / 255
                let mx = max(r, max(g, b)), mn = min(r, min(g, b)), d = mx - mn
                var yes = false
                if mx >= 0.45 && d / max(mx, 1e-6) >= 0.5 && b < r && b < g {
                    var hue: Float = mx == r ? 60 * ((g - b) / d) : 60 * ((b - r) / d + 2)
                    if hue < 0 { hue += 360 }
                    yes = hue >= 45 && hue <= 70
                }
                mask[gy * gw + gx] = yes ? 1 : 0
            }
        }
        // connected blobs; neighbours up to 2 cells apart join, so one object split by glare stays one blob
        var blobs: [Blob] = []
        var stack: [Int] = []
        for i in 0..<(gw * gh) where mask[i] == 1 {
            var bl = Blob()
            mask[i] = 2; stack.append(i)
            while let j = stack.popLast() {
                let x = j % gw, y = j / gw
                bl.n += 1; bl.sx += Double(x); bl.sy += Double(y)
                bl.minX = min(bl.minX, x); bl.maxX = max(bl.maxX, x); bl.minY = min(bl.minY, y); bl.maxY = max(bl.maxY, y)
                for dy in -2...2 { for dx in -2...2 {
                    let nx = x + dx, ny = y + dy
                    if nx >= 0 && nx < gw && ny >= 0 && ny < gh { let k = ny * gw + nx; if mask[k] == 1 { mask[k] = 2; stack.append(k) } }
                } }
            }
            if bl.n >= 6 { blobs.append(bl) }
        }
        return (blobs, gw * gh, gw, gh)
    }

    // Pick the target blob: while locked, only the blob near the last target with a similar size counts.
    func chooseTarget(_ blobs: [Blob], total: Int, gw: Int, gh: Int) -> (cx: Double, cy: Double, size: Double, n: Int, box: CGRect, how: String)? {
        func info(_ b: Blob) -> (Double, Double, Double, CGRect) {
            let cx = (b.sx / Double(b.n) + 0.5) / Double(gw), cy = (b.sy / Double(b.n) + 0.5) / Double(gh)
            let box = CGRect(x: CGFloat(b.minX) / CGFloat(gw), y: 1 - CGFloat(b.maxY + 1) / CGFloat(gh),
                             width: CGFloat(b.maxX - b.minX + 1) / CGFloat(gw), height: CGFloat(b.maxY - b.minY + 1) / CGFloat(gh))
            return (cx, cy, (Double(b.n) / Double(total)).squareRoot(), box)
        }
        lastBlobs = blobs.map { info($0).3 }
        let now = Date()
        if now.timeIntervalSince(trackLast) < LOCK_HOLD && trackS > 0 {          // locked: gate around the last target
            var best: (Double, Blob)? = nil
            for b in blobs {
                let (cx, cy, sz, _) = info(b)
                let dist = ((cx - trackCx) * (cx - trackCx) + (cy - trackCy) * (cy - trackCy)).squareRoot()
                let ratio = sz / trackS
                if dist > GATE || ratio < 0.45 || ratio > 2.2 || sz < KEEP_MIN { continue }
                let score = dist + 0.25 * abs(log(ratio))
                if best == nil || score < best!.0 { best = (score, b) }
            }
            guard let b = best?.1 else { return nil }                          // target hidden: hold, don't switch
            let (cx, cy, sz, box) = info(b)
            trackCx = cx; trackCy = cy; trackS = sz; trackLast = now
            return (cx, cy, sz, b.n, box, blobs.count > 1 ? "locked, ignoring \(blobs.count - 1) other" : "locked")
        }
        guard let big = blobs.max(by: { $0.n < $1.n }) else { return nil }    // (re)acquire: the biggest yellow blob
        let (cx, cy, sz, box) = info(big)
        if sz < ACQ_MIN { return nil }                                       // ...but only if it's big enough to be the target
        trackCx = cx; trackCy = cy; trackS = sz; trackLast = now
        return (cx, cy, sz, big.n, box, "acquired")
    }

    func followYellow(_ pb: CVPixelBuffer) {
        let (blobs, total, gw, gh) = yellowBlobs(pb)
        let t = chooseTarget(blobs, total: total, gw: gw, gh: gh)
        if let r = t {
            lastSeen = Date(); yellowBox = r.box
            let ex = r.cx - 0.5
            var wCmd = abs(ex) < DEAD_X ? 0 : -2.5 * ex                  // yellow on the right -> turn right
            // speed from the distance RATIO: patch size ~ 1/distance, so target/size - 1 = how many times too far
            let ratio = targetY / max(r.size, 0.01) - 1
            var vCmd = abs(ratio) < 0.08 ? 0 : 0.35 * ratio               // twice as far as wanted -> 0.35 m/s
            if turnOnly { vCmd = 0 }
            vCmd = max(-0.15, min(followVmax, vCmd)); wCmd = max(-1.2, min(1.2, wCmd))
            if cameraBack { vCmd = -vCmd }
            v = 0.6 * v + 0.4 * vCmd; w = 0.6 * w + 0.4 * wCmd
        } else if Date().timeIntervalSince(lastSeen) > LOST_AFTER { v = 0; w = 0 }
        if !dry { post(v: v, w: w, found: t != nil, cx: t?.cx ?? 0.5, h: t?.size ?? 0) }
        let now = Date()
        if now.timeIntervalSince(lastPrint) > 0.5 {
            lastPrint = now
            if let r = t { print(String(format: "yellow: offset %+.2f  size %.3f  [%@]  ->  speed %+.2f m/s  turn %+.2f rad/s", r.cx - 0.5, r.size, r.how, v, w)) }
            else { print(blobs.isEmpty ? "no yellow in view" : "no target (\(blobs.count) yellow thing\(blobs.count > 1 ? "s" : "") in view, ignored: too small or not the locked one)") }
        }
        if now.timeIntervalSince(lastSnap) > 1.0 { lastSnap = now; snapshot(pb, people: [], best: nil, extra: t != nil ? yellowBox : nil) }
    }

    func post(v: Double, w: Double, found: Bool, cx: Double, h: Double) {
        var r = URLRequest(url: URL(string: "http://127.0.0.1:8765/auto")!)
        r.httpMethod = "POST"; r.timeoutInterval = 0.2
        r.httpBody = try? JSONSerialization.data(withJSONObject: ["v": v, "w": w, "found": found, "cx": cx, "h": h])
        URLSession.shared.dataTask(with: r).resume()
    }

    func snapshot(_ pb: CVPixelBuffer, people: [VNHumanObservation], best: VNHumanObservation?, extra: CGRect? = nil) {
        let ci = CIImage(cvPixelBuffer: pb).oriented(rotation)
        guard let cg = ciContext.createCGImage(ci, from: ci.extent) else { return }
        let W = cg.width, H = cg.height
        guard let ctx = CGContext(data: nil, width: W, height: H, bitsPerComponent: 8, bytesPerRow: 0,
                                  space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue) else { return }
        ctx.draw(cg, in: CGRect(x: 0, y: 0, width: W, height: H))
        ctx.setLineWidth(4)
        for p in people {                                   // Vision boxes are normalized, origin bottom-left (same as CGContext)
            let b = p.boundingBox
            ctx.setStrokeColor(p === best ? CGColor(red: 0.1, green: 0.9, blue: 0.2, alpha: 1) : CGColor(red: 1, green: 0.8, blue: 0, alpha: 1))
            ctx.stroke(CGRect(x: b.minX * CGFloat(W), y: b.minY * CGFloat(H), width: b.width * CGFloat(W), height: b.height * CGFloat(H)))
        }
        ctx.setStrokeColor(CGColor(red: 1, green: 0.55, blue: 0, alpha: 1)); ctx.setLineWidth(3)   // all yellow blobs (orange)
        if yellowMode { for e in lastBlobs { ctx.stroke(CGRect(x: e.minX * CGFloat(W), y: e.minY * CGFloat(H), width: e.width * CGFloat(W), height: e.height * CGFloat(H))) } }
        if let e = extra {                                  // yellow target box
            ctx.setStrokeColor(CGColor(red: 0.1, green: 0.9, blue: 0.2, alpha: 1)); ctx.setLineWidth(5)
            ctx.stroke(CGRect(x: e.minX * CGFloat(W), y: e.minY * CGFloat(H), width: e.width * CGFloat(W), height: e.height * CGFloat(H)))
        }
        ctx.setStrokeColor(CGColor(red: 1, green: 1, blue: 1, alpha: 0.6)); ctx.setLineWidth(2)
        ctx.stroke(CGRect(x: CGFloat(W) / 2, y: 0, width: 0.1, height: CGFloat(H)))   // center line
        guard let outImg = ctx.makeImage(),
              let jpg = NSBitmapImageRep(cgImage: outImg).representation(using: .jpeg, properties: [.compressionFactor: 0.6]) else { return }
        try? jpg.write(to: URL(fileURLWithPath: snapPath))
    }
}

AVCaptureDevice.requestAccess(for: .video) { ok in
    if !ok { print("Camera access denied. System Settings > Privacy & Security > Camera: allow Terminal."); exit(1) }
    DispatchQueue.main.async {
        let f = Follower()
        f.start()
        objc_setAssociatedObject(NSApplication.shared, "follower", f, .OBJC_ASSOCIATION_RETAIN)
        print("Saving what it sees to \(snapPath) every second. Ctrl+C to stop.")
    }
}
signal(SIGINT) { _ in
    // stop driving immediately on Ctrl+C
    var r = URLRequest(url: URL(string: "http://127.0.0.1:8765/auto")!)
    r.httpMethod = "POST"; r.httpBody = "{\"v\":0,\"w\":0}".data(using: .utf8)
    let sem = DispatchSemaphore(value: 0)
    URLSession.shared.dataTask(with: r) { _, _, _ in sem.signal() }.resume()
    _ = sem.wait(timeout: .now() + 0.3)
    exit(0)
}
dispatchMain()
