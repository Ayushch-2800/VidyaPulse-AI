"use client";

import { useEffect, useImperativeHandle, useRef, useState } from "react";

import {
  extractYouTubeId,
  loadYouTubeApi,
  type YouTubePlayer,
} from "@/lib/youtube";

export type LectureMedia =
  { kind: "youtube"; url: string } | { kind: "file"; url: string };

export type LecturePlayerHandle = {
  seek: (seconds: number) => void;
  getCurrentTime: () => number;
};

const AUDIO_EXTENSIONS = /\.(mp3|m4a|aac|wav|ogg|oga|opus|flac|weba)$/i;

// The YouTube API has no time events, so poll it this often for the transcript sync
const YOUTUBE_POLL_MS = 250;

/** True when the URL's path (ignoring a signed URL's query string) names an audio file. */
export function isAudioUrl(url: string): boolean {
  try {
    return AUDIO_EXTENSIONS.test(new URL(url, "http://local").pathname);
  } catch {
    return false;
  }
}

/**
 * Plays a lecture from YouTube or a media file URL, exposes seek(seconds) so
 * CitedAnswer's [MM:SS] buttons can jump the player, and reports the playback
 * position through onTimeUpdate so the transcript can follow along.
 */
export default function LecturePlayer({
  media,
  startAt = 0,
  onTimeUpdate,
  ref,
}: {
  media: LectureMedia;
  /** Where to resume, in seconds, when the player first loads */
  startAt?: number;
  onTimeUpdate?: (seconds: number) => void;
  ref?: React.Ref<LecturePlayerHandle>;
}) {
  const youtubeHost = useRef<HTMLDivElement>(null);
  const youtubePlayer = useRef<YouTubePlayer | null>(null);
  const mediaElement = useRef<HTMLMediaElement>(null);
  // Set when a file we expected to be video turns out to have no picture
  const [noVideoTrack, setNoVideoTrack] = useState(false);
  const reportTime = useRef(onTimeUpdate);
  // Read once: later position updates must not reload the player
  const resumeAt = useRef(Math.max(0, Math.floor(startAt)));

  useEffect(() => {
    reportTime.current = onTimeUpdate;
  }, [onTimeUpdate]);

  const videoId = media.kind === "youtube" ? extractYouTubeId(media.url) : null;
  const audioOnly =
    media.kind === "file" && (isAudioUrl(media.url) || noVideoTrack);

  useEffect(() => {
    if (!videoId || !youtubeHost.current) return;
    let cancelled = false;
    let lastTime = -1;
    // The YouTube API replaces the element it is given, so hand it a child we own
    const target = document.createElement("div");
    youtubeHost.current.replaceChildren(target);

    loadYouTubeApi().then((YT) => {
      if (cancelled) return;
      youtubePlayer.current = new YT.Player(target, {
        videoId,
        width: "100%",
        height: "100%",
        playerVars: resumeAt.current ? { start: resumeAt.current } : undefined,
      });
    });

    const poll = window.setInterval(() => {
      // getCurrentTime only exists once the player has finished loading
      const time = youtubePlayer.current?.getCurrentTime?.();
      if (typeof time === "number" && time !== lastTime) {
        lastTime = time;
        reportTime.current?.(time);
      }
    }, YOUTUBE_POLL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(poll);
      youtubePlayer.current?.destroy();
      youtubePlayer.current = null;
    };
  }, [videoId]);

  useImperativeHandle(ref, () => ({
    seek(seconds: number) {
      if (youtubePlayer.current) {
        youtubePlayer.current.seekTo(seconds, true);
        youtubePlayer.current.playVideo();
        reportTime.current?.(seconds);
      } else if (mediaElement.current) {
        mediaElement.current.currentTime = seconds;
        void mediaElement.current.play();
      }
    },
    getCurrentTime() {
      if (youtubePlayer.current?.getCurrentTime) {
        return youtubePlayer.current.getCurrentTime();
      }
      return mediaElement.current?.currentTime ?? 0;
    },
  }));

  if (media.kind === "youtube" && !videoId) {
    return (
      <p style={{ color: "var(--vp-danger)" }}>
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
          borderRadius: "18px",
          overflow: "hidden",
          border: "1px solid var(--vp-border)",
          boxShadow: "var(--vp-shadow)",
        }}
      />
    );
  }

  const mediaEvents = {
    onLoadedMetadata: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      const element = e.currentTarget;
      if (resumeAt.current && element.currentTime === 0) {
        element.currentTime = Math.min(
          resumeAt.current,
          element.duration || resumeAt.current,
        );
      }
      // No extension to go on (e.g. a bare signed URL), so check for a picture once loaded
      if (element instanceof HTMLVideoElement && element.videoWidth === 0)
        setNoVideoTrack(true);
    },
    onTimeUpdate: (e: React.SyntheticEvent<HTMLMediaElement>) =>
      reportTime.current?.(e.currentTarget.currentTime),
    onSeeked: (e: React.SyntheticEvent<HTMLMediaElement>) =>
      reportTime.current?.(e.currentTarget.currentTime),
  };

  if (audioOnly) {
    return (
      <div
        style={{
          padding: "16px",
          border: "1px solid var(--vp-border)",
          borderRadius: "18px",
          backgroundColor: "var(--vp-surface)",
        }}
      >
        <p
          style={{
            margin: "0 0 8px 0",
            color: "var(--vp-muted)",
            fontSize: "0.9em",
          }}
        >
          🎧 Audio lecture
        </p>
        <audio
          ref={(el) => {
            mediaElement.current = el;
          }}
          src={media.url}
          controls
          preload="metadata"
          style={{ width: "100%" }}
          {...mediaEvents}
        />
      </div>
    );
  }

  return (
    <video
      ref={(el) => {
        mediaElement.current = el;
      }}
      src={media.url}
      controls
      preload="metadata"
      style={{
        width: "100%",
        maxHeight: "360px",
        backgroundColor: "#000",
        borderRadius: "18px",
        border: "1px solid var(--vp-border)",
      }}
      {...mediaEvents}
    />
  );
}
