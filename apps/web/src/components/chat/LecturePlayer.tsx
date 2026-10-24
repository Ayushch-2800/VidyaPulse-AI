"use client";

import { useEffect, useImperativeHandle, useRef } from "react";

import {
  extractYouTubeId,
  loadYouTubeApi,
  type YouTubePlayer,
} from "@/lib/youtube";

export type LectureMedia =
  { kind: "youtube"; url: string } | { kind: "file"; url: string };

export type LecturePlayerHandle = { seek: (seconds: number) => void };

/**
 * Plays a lecture from YouTube or a media file URL and exposes seek(seconds)
 * so CitedAnswer's [MM:SS] buttons can jump the player to a timestamp.
 */
export default function LecturePlayer({
  media,
  ref,
}: {
  media: LectureMedia;
  ref?: React.Ref<LecturePlayerHandle>;
}) {
  const youtubeHost = useRef<HTMLDivElement>(null);
  const youtubePlayer = useRef<YouTubePlayer | null>(null);
  const mediaElement = useRef<HTMLVideoElement>(null);

  const videoId = media.kind === "youtube" ? extractYouTubeId(media.url) : null;

  useEffect(() => {
    if (!videoId || !youtubeHost.current) return;
    let cancelled = false;
    // The YouTube API replaces the element it is given, so hand it a child we own
    const target = document.createElement("div");
    youtubeHost.current.replaceChildren(target);

    loadYouTubeApi().then((YT) => {
      if (cancelled) return;
      youtubePlayer.current = new YT.Player(target, {
        videoId,
        width: "100%",
        height: "100%",
      });
    });

    return () => {
      cancelled = true;
      youtubePlayer.current?.destroy();
      youtubePlayer.current = null;
    };
  }, [videoId]);

  useImperativeHandle(ref, () => ({
    seek(seconds: number) {
      if (youtubePlayer.current) {
        youtubePlayer.current.seekTo(seconds, true);
        youtubePlayer.current.playVideo();
      } else if (mediaElement.current) {
        mediaElement.current.currentTime = seconds;
        void mediaElement.current.play();
      }
    },
  }));

  if (media.kind === "youtube" && !videoId) {
    return (
      <p style={{ color: "#B91C1C" }}>
        Could not read a YouTube video ID from {media.url}
      </p>
    );
  }

  if (media.kind === "youtube") {
    return (
      <div
        ref={youtubeHost}
        style={{
          aspectRatio: "16 / 9",
          width: "100%",
          backgroundColor: "#000",
          borderRadius: "8px",
          overflow: "hidden",
        }}
      />
    );
  }

  // A <video> element also plays audio-only files such as the uploaded MP3s
  return (
    <video
      ref={mediaElement}
      src={media.url}
      controls
      style={{
        width: "100%",
        maxHeight: "360px",
        backgroundColor: "#000",
        borderRadius: "8px",
      }}
    />
  );
}
