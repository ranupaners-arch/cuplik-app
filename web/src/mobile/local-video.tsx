import { type CSSProperties, useState } from "react";

export function LocalVideo({ src, width, height, label }: { src: string; width?: number; height?: number; label: string }) {
  const [measured, setMeasured] = useState<{ src: string; ratio: number }>();
  const known = width && height && width > 0 && height > 0 ? width / height : undefined;
  const ratio = known ?? (measured?.src === src ? measured.ratio : 16 / 9);
  return <video controls playsInline preload="metadata" aria-label={label} src={src}
    style={{ "--video-ratio": ratio, aspectRatio: String(ratio) } as CSSProperties}
    onLoadedMetadata={event => {
      const video = event.currentTarget;
      if (video.videoWidth > 0 && video.videoHeight > 0) setMeasured({ src, ratio: video.videoWidth / video.videoHeight });
    }} />;
}
