import os
import glob
import pysrt
import re
import subprocess
import multiprocessing
import concurrent.futures
from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip
import imageio_ffmpeg

DEFAULT_TARGET_DIR = r""
ORIGINAL_AUDIO_VOLUME = 0.1
MAX_WORKERS = 1
MAX_CLUSTER_GAP = 1.5

tts_instance = None

def time_to_seconds(time_obj):
    return time_obj.hours * 3600 + time_obj.minutes * 60 + time_obj.seconds + time_obj.milliseconds / 1000.0

def init_worker():
    global tts_instance
    os.environ["OMP_NUM_THREADS"] = "4"
    from vieneu import Vieneu
    tts_instance = Vieneu()

def process_subtitle(task_data):
    i, text, start_time, e_time, total, temp_dir = task_data
    global tts_instance
    
    raw_audio_file = os.path.join(temp_dir, f"temp_dub_raw_{i}.wav")
    print(f"   [{i+1}/{total}] [Worker {os.getpid()}] sinh âm: {text[:30]}...")
    
    audio = tts_instance.infer(text=text)
    tts_instance.save(audio, raw_audio_file)
    
    char_len = len(text)
    
    if not os.path.exists(raw_audio_file) or os.path.getsize(raw_audio_file) < 100:
        return i, None, start_time, e_time, 0, char_len
        
    clip = AudioFileClip(raw_audio_file)
    duration = clip.duration
    
    # CHỐNG ẢO GIÁC (ANTI-HALLUCINATION)
    max_safe_duration = (char_len / 8.0) + 1.5
    if duration > max_safe_duration:
        print(f"   -> [Cắt Ảo giác] Đoạn '{text[:15]}...' bị AI rên rỉ tới {duration:.1f}s. Đã chém đuôi còn {max_safe_duration:.1f}s!")
        trimmed_clip = clip.subclipped(0, max_safe_duration)
        temp_trim_name = raw_audio_file.replace(".wav", "_trim.wav")
        trimmed_clip.write_audiofile(temp_trim_name, fps=24000, logger=None)
        clip.close()
        trimmed_clip.close()
        os.remove(raw_audio_file)
        os.rename(temp_trim_name, raw_audio_file)
        duration = max_safe_duration
    else:
        clip.close()
        
    return i, raw_audio_file, start_time, e_time, duration, char_len

def build_atempo_chain(factor):
    filters = []
    f = factor
    while f > 2.0:
        filters.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        filters.append("atempo=0.5")
        f /= 0.5
    if f != 1.0:
        filters.append(f"atempo={f:.3f}")
    return ",".join(filters)

def process_single_video(executor, video_file, sub_file, out_file):
    print(f"\n==================================================")
    print(f"ĐANG XỬ LÝ (SMART CLUSTER SYNC - GOM CỤM): {os.path.basename(video_file)}")
    print(f"==================================================")
    
    base_name = os.path.splitext(os.path.basename(video_file))[0]
    temp_dir = os.path.join(os.path.dirname(video_file), f"temp_{base_name}")
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        
    subs = pysrt.open(sub_file, encoding='utf-8')
    temp_files = []
    tasks = []
    
    for i, sub in enumerate(subs):
        text = sub.text.replace('\n', ' ')
        text = re.sub(r'^[-:\s]+', '', text).strip()
        start_time = time_to_seconds(sub.start)
        e_time = time_to_seconds(sub.end)
        if text:
            tasks.append((i, text, start_time, e_time, len(subs), temp_dir))
    
    print(f"-> Phân rã {len(tasks)} câu hội thoại cho AI xử lý...")
    results_raw = []
    
    for result in executor.map(process_subtitle, tasks):
        i, raw_audio_file, start_time, e_time, duration, char_len = result
        if raw_audio_file:
            results_raw.append((i, raw_audio_file, start_time, e_time, duration, char_len))
            temp_files.append(raw_audio_file)

    results_raw.sort(key=lambda x: x[0])
    video = VideoFileClip(video_file)
    
    # -------------------------------------------------------------
    # THUẬT TOÁN GOM NHÓM (CLUSTERING) & TÁI PHÂN BỔ TỈ LỆ (NORMALIZATION)
    # -------------------------------------------------------------
    clusters = []
    current_cluster = []
    
    for item in results_raw:
        s_time = item[2]
        if not current_cluster:
            current_cluster.append(item)
        else:
            prev_e_time = current_cluster[-1][3]
            if s_time - prev_e_time <= MAX_CLUSTER_GAP:
                current_cluster.append(item)
            else:
                clusters.append(current_cluster)
                current_cluster = [item]
    if current_cluster:
        clusters.append(current_cluster)
        
    print(f"-> Đã gom {len(results_raw)} đoạn hội thoại thành {len(clusters)} Cluster Cục bộ.")
    
    normalized_results = []
    for cluster in clusters:
        total_chars = sum(item[5] for item in cluster)
        c_start = cluster[0][2]
        # Tìm e_time lớn nhất trong Cluster để xác định ranh giới Đáy
        c_end = max(item[3] for item in cluster) 
        cluster_pool = c_end - c_start
        
        current_s_time = c_start
        
        for item in cluster:
            i, f_path, old_s, old_e, duration, char_len = item
            # Phân tách quỹ thời gian theo đóng góp chữ số
            ratio = char_len / total_chars if total_chars > 0 else 1.0
            allocated_slot = cluster_pool * ratio
            
            new_s_time = current_s_time
            new_e_time = current_s_time + allocated_slot
            
            normalized_results.append((i, f_path, new_s_time, new_e_time, duration))
            current_s_time = new_e_time # Chuyển mốc thời gian cho câu tiếp theo

    # -------------------------------------------------------------
    # THI HÀNH ÉP FFmpeg LOCAL DỰA VÀO BIÊN ĐỘ TÁI PHÂN BỔ MỚI
    # -------------------------------------------------------------
    processed_results = []
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    
    print("-> Điều chỉnh Tốc độ (Cân bằng tỉ lệ Phân bổ)...")
    for i, f_path, s_time, e_time, duration in normalized_results:
        # Mục đích: chừa 0.15s bắt buộc nhấn nhá ở đuôi câu
        target_duration = max(0.2, (e_time - s_time) - 0.15)
        
        factor = duration / target_duration
        factor = max(0.5, min(3.5, factor))
        
        if 0.95 <= factor <= 1.05:
            processed_results.append((i, f_path, s_time, e_time, duration))
        else:
            atempo_str = build_atempo_chain(factor)
            out_file_temp = os.path.join(temp_dir, f"temp_dub_sync_{i}.wav")
            subprocess.run([
                ffmpeg_exe, "-y", "-i", f_path, 
                "-filter:a", atempo_str, 
                out_file_temp
            ], capture_output=True)
            temp_files.append(out_file_temp)
            processed_results.append((i, out_file_temp, s_time, e_time, duration / factor))
            
    print("-> Giảm Volume Âm nền...")
    bg_low_file = os.path.join(temp_dir, "temp_bg_low.wav")
    if video.audio is not None:
        bg_audio_reduced = video.audio.with_volume_scaled(ORIGINAL_AUDIO_VOLUME)
        bg_audio_reduced.write_audiofile(bg_low_file, fps=24000, logger=None)
        temp_files.append(bg_low_file)
        bg_final_clip = AudioFileClip(bg_low_file)
    else:
        bg_final_clip = None

    print("-> Sáp nhập Khớp trục Smart Timeline Mode...")
    dubbed_clips = []
    for i, f_path, s_time, e_time, duration in processed_results:
        clip = AudioFileClip(f_path)
        dubbed_clips.append(clip.with_start(s_time))
        
    tracks_to_mix = [bg_final_clip] + dubbed_clips if bg_final_clip else dubbed_clips
    final_audio = CompositeAudioClip(tracks_to_mix)
    
    temp_master_audio = os.path.join(temp_dir, "temp_master_audio.wav")
    final_audio.write_audiofile(temp_master_audio, fps=24000, logger=None)
    temp_files.append(temp_master_audio)
    
    print("-> Render Video Final HD...")
    process = subprocess.run([
        ffmpeg_exe, "-y",
        "-i", video_file,
        "-i", temp_master_audio,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        out_file
    ], capture_output=True, text=True)
    
    if process.returncode != 0:
        print("\n[LỖI FFMPEG]:", process.stderr)
    else:
        print(f"SUCCESSS: Đã xuất file Khớp cứng Mượt mà Audio-Video ({os.path.basename(out_file)})!")
        
    for clip in dubbed_clips: clip.close()
    if bg_final_clip: bg_final_clip.close()
    final_audio.close()
    video.close()
    
    for f in temp_files:
        try: os.remove(f)
        except: pass
    try: os.rmdir(temp_dir)
    except: pass


def main():
    print("================================================================")
    print(" HỆ THỐNG XỬ LÝ VIDEO AUTO_DUB_SMART - [TÁI PHÂN BỐ CLUSTER]    ")
    print("================================================================")
    
    target_dir = input(f"Nhập đường dẫn Thư mục'{DEFAULT_TARGET_DIR}'): ").strip()
    if not target_dir:
        target_dir = DEFAULT_TARGET_DIR
        
    if not os.path.isdir(target_dir):
        print(f"Tuyệt đối không tìm thấy đường dẫn: {target_dir}")
        return
        
    print(f"\n[SCAN] Quét tìm MP4 tại {target_dir} ...")
    search_pattern = os.path.join(target_dir, "*.mp4")
    mp4_files = glob.glob(search_pattern)
    
    video_pairs = []
    for mp4 in mp4_files:
        if mp4.endswith("_dubbed.mp4"): continue 
        base_name = os.path.splitext(mp4)[0]
        srt_file = base_name + "_vi.srt"
        out_mp4 = base_name + "_dubbed.mp4"
        if os.path.exists(srt_file):
            video_pairs.append((mp4, srt_file, out_mp4))
            
    if not video_pairs:
        print("KHÔNG TÌM ĐƯỢC TASK NÀO SAU KHI SÀNG LỌC.")
        return
        
    print(f"Đã đóng hợp đồng {len(video_pairs)} Video cần Lồng tiếng!")
    
    with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS, initializer=init_worker) as executor:
        for idx, (v, s, o) in enumerate(video_pairs):
            print(f"\n[+] Processing Frame-By-Frame Cluster Timeline: {idx+1}/{len(video_pairs)}")
            try:
                process_single_video(executor, v, s, o)
            except Exception as e:
                print(f" [LỖI NGUY HIỂM] Video {os.path.basename(v)} dính Exception: {e}")
                
    print("\n================================================================")
    print("Hoàn tất quy trình Render. Mọi âm thanh đã được chuẩn hóa Dịch Time!")
    print("================================================================")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
