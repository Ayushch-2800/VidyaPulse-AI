import cv2
import os
import uuid
from skimage.metrics import structural_similarity as ssim
from storage_utils import supabase
from ocr_engine import extract_visual_data

# Use existing temp directory
TEMP_DIR = "temp_chunks"
os.makedirs(TEMP_DIR, exist_ok=True)


def process_and_index_keyframes(keyframe_paths: list, timestamps: list) -> list:
    """
    Iterates over extracted keyframes, runs multimodal OCR, and bundles the payloads.
    """
    indexed_visual_payloads = []

    print(
        f"[VISION PIPELINE]: Running OCR extraction on {len(keyframe_paths)} keyframes..."
    )

    for path, ts in zip(keyframe_paths, timestamps):
        print(f"Processing frame at {ts}s...")

        # Call the VLM OCR service
        visual_data = extract_visual_data(image_path=path, timestamp=ts)

        if visual_data["extracted_content"]:
            indexed_visual_payloads.append(visual_data)

    print("[VISION PIPELINE]: Visual OCR processing complete.")
    return indexed_visual_payloads


def process_video_keyframes(
    video_path: str, lecture_id: str, user_id: str, ssim_threshold: float = 0.85
):
    """
    Extracts high-value keyframes from a video using SSIM, runs the VLM OCR pipeline,
    uploads to Supabase 'lecture-keyframes' bucket, and logs metadata to the DB.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_skip = int(fps)  # Sample 1 frame per second to optimize performance

    ret, prev_frame = cap.read()
    if not ret:
        cap.release()
        return []

    # Convert initial frame to grayscale for SSIM comparison
    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)

    current_frame_pos = 0
    local_keyframe_paths = []
    keyframe_timestamps = []

    print("[VISION PIPELINE]: Starting SSIM keyframe extraction...")

    # Force save the very first frame of the video
    first_path = _save_frame_locally(prev_frame)
    local_keyframe_paths.append(first_path)
    keyframe_timestamps.append(0.0)

    while True:
        # Jump ahead by `frame_skip`
        current_frame_pos += frame_skip
        cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame_pos)

        ret, curr_frame = cap.read()
        if not ret:
            break  # End of video

        curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)

        # Calculate structural similarity index
        score, _ = ssim(prev_gray, curr_gray, full=True)

        if score < ssim_threshold:
            # Significant visual change detected (slide change, whiteboard wipe)
            timestamp_sec = current_frame_pos / fps
            path = _save_frame_locally(curr_frame)

            local_keyframe_paths.append(path)
            keyframe_timestamps.append(timestamp_sec)

            # Reset the comparison baseline to this new keyframe
            prev_gray = curr_gray

    cap.release()

    # 1. Run the integrated OCR pipeline on all extracted local frames
    ocr_results = process_and_index_keyframes(local_keyframe_paths, keyframe_timestamps)

    # Create a quick dictionary lookup to match image paths with their extracted text
    ocr_lookup = {item["image_path"]: item["extracted_content"] for item in ocr_results}

    # 2. Upload to Supabase and gather final database payloads
    saved_keyframes = []
    print("[VISION PIPELINE]: Uploading keyframes to Supabase Storage...")

    for path, ts in zip(local_keyframe_paths, keyframe_timestamps):
        extracted_text = ocr_lookup.get(path, "")
        frame_metadata = _upload_frame_and_cleanup(
            path, ts, lecture_id, user_id, extracted_text
        )
        saved_keyframes.append(frame_metadata)

    # 3. Bulk insert keyframe metadata (including the extracted text) into database
    if saved_keyframes:
        supabase.table("keyframes").insert(saved_keyframes).execute()
        print(
            f"[VISION PIPELINE]: Successfully indexed {len(saved_keyframes)} keyframes in Supabase."
        )

    return saved_keyframes


def _save_frame_locally(frame) -> str:
    """Helper to temporarily save an OpenCV frame to disk for OCR processing."""
    unique_id = str(uuid.uuid4())
    filename = f"{unique_id}.jpg"
    local_path = os.path.join(TEMP_DIR, filename)

    # Compress frame to JPEG (75% quality for optimal size/clarity ratio)
    cv2.imwrite(local_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    return local_path


def _upload_frame_and_cleanup(
    local_path: str,
    timestamp_sec: float,
    lecture_id: str,
    user_id: str,
    extracted_text: str,
):
    """Uploads the local keyframe image to Supabase, deletes it, and returns the metadata."""
    filename = os.path.basename(local_path)
    bucket_path = f"{user_id}/{lecture_id}/{filename}"

    with open(local_path, "rb") as f:
        supabase.storage.from_("lecture-keyframes").upload(
            path=bucket_path, file=f, file_options={"content-type": "image/jpeg"}
        )

    # Clean up local compressed image to save disk space
    os.remove(local_path)

    return {
        "lecture_id": lecture_id,
        "timestamp_seconds": round(timestamp_sec, 2),
        "storage_path": bucket_path,
        "extracted_text": extracted_text,
    }
