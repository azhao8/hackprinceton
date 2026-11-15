import { Config } from "@remotion/cli/config";

// Frames are rendered in the installed Google Chrome (the headless shell Remotion downloads
// doesn't start on this Mac); see tools/render.sh.
Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(96);
