# Hệ Thống Lồng Tiếng Video Tự Động (Auto Video Dubbing System)

Dự án này là một công cụ tự động hóa toàn diện quy trình lồng tiếng cho video. Bằng việc kết hợp file video gốc (MP4) và file phụ đề (SRT), hệ thống sử dụng công nghệ Text-To-Speech (TTS) để tạo ra giọng đọc và ghép nối chúng một cách hoàn hảo vào video. Điểm nổi bật nhất của dự án là **Thuật toán Đồng bộ Thông minh (Smart Cluster Sync)** giúp giữ được sự tự nhiên của giọng đọc mà vẫn đảm bảo khớp môi (lip-sync).

---

## 🛠 1. Công Nghệ Sử Dụng

Dự án được xây dựng dựa trên các công nghệ và thư viện mã nguồn mở mạnh mẽ của Python:

* **Python 3.x**: Ngôn ngữ lập trình cốt lõi.
* **Vieneu TTS**: Mô hình trí tuệ nhân tạo Text-to-Speech chạy cục bộ, chuyên dùng để tổng hợp giọng nói tiếng Việt tự nhiên.
* **FFmpeg & `imageio_ffmpeg`**: Bộ công cụ "xương sống" dùng để xử lý, cắt ghép, thay đổi tốc độ (atempo) và kết hợp các luồng Audio/Video.
* **MoviePy**: Thư viện dùng để tính toán thời lượng và mix (trộn) các track âm thanh lại với nhau (giữ lại âm nền của video).
* **pysrt**: Thư viện dùng để đọc, phân tích cú pháp (parse) và trích xuất thời gian từ file phụ đề `.srt`.
* **Multiprocessing & Concurrent.futures**: Tối ưu hóa hiệu suất bằng cách tận dụng tối đa CPU để sinh audio song song đa tiến trình.

---

## 🧠 2. Thuật Toán Cốt Lõi (Core Algorithms)

Để giải quyết bài toán lồng tiếng bị "đơ" hoặc đọc quá nhanh/quá chậm, hệ thống áp dụng các thuật toán nâng cao:

### 🌟 Smart Cluster Normalization (Gom cụm và Tái phân bổ thời gian)
Thay vì bắt AI phải đọc khớp chính xác đến từng mili-giây của từng dòng phụ đề (điều này thường khiến giọng đọc bị méo mó, không tự nhiên), thuật toán này hoạt động như sau:
1. **Gom cụm (Clustering):** Gom các dòng phụ đề xuất hiện sát nhau (khoảng cách `< 1.5s`) thành một "Cluster" (Khối hội thoại).
2. **Đo đạc quỹ thời gian:** Tính toán khoảng thời gian từ lúc bắt đầu câu đầu tiên đến lúc kết thúc câu cuối cùng trong Cluster đó.
3. **Tái phân bổ (Normalization):** Dựa vào số lượng chữ (characters) của từng câu, hệ thống chia lại "miếng bánh" thời gian một cách công bằng. Câu dài sẽ có nhiều thời gian để đọc hơn, câu ngắn sẽ đọc nhanh hơn một chút, giúp luồng âm thanh trôi chảy mượt mà mà **không làm thay đổi tổng thời lượng của cả phân đoạn**.

### 🛡 Anti-Hallucination (Thuật toán chống ảo giác AI)
Các mô hình TTS đôi khi bị lỗi "ảo giác" (hallucination), tự sinh ra các âm thanh rên rỉ hoặc âm câm kéo dài ở cuối câu.
* Thuật toán sẽ tính toán **Thời gian an toàn tối đa** (`max_safe_duration = (số chữ / 8.0) + 1.5s`).
* Nếu file audio sinh ra dài hơn ngưỡng này, hệ thống sẽ tự động dùng "dao" cắt bỏ phần âm thanh thừa ở đuôi để bảo vệ tiến trình đồng bộ.

### 🎛 FFmpeg Dynamic Atempo (Khớp nối trục thời gian)
Sau khi có phân bổ thời gian lý tưởng từ thuật toán *Smart Cluster*, hệ thống gọi `FFmpeg` để áp dụng bộ lọc âm thanh `atempo`:
* Kéo dãn hoặc nén âm thanh gốc sao cho khớp khít với khoảng thời gian mới.
* Các giới hạn giãn/nén an toàn (0.5x đến 3.5x) được áp dụng để đảm bảo tiếng không bị méo.

### 🎧 Smart Background Audio Mixing
* Hệ thống sẽ trích xuất âm thanh gốc của video.
* Giảm âm lượng (Volume) của âm thanh gốc xuống mức nhỏ (10% - `ORIGINAL_AUDIO_VOLUME = 0.1`) để tạo thành nhạc nền (Background Music).
* Trộn (Mix) giọng đọc của AI đè lên trên, mang lại cảm giác chuyên nghiệp như studio lồng tiếng.

---

## 📂 3. Cấu Trúc File Đầu Vào
Hệ thống nhận diện file theo cặp dựa vào tên.
* **File Video**: `Ten_Video.mp4`
* **File Phụ đề**: `Ten_Video_vi.srt` (Bắt buộc phải có đuôi `_vi.srt`)

**Ví dụ:**
```text
Thư mục dự án/
├── 01. Introduction.mp4
├── 01. Introduction_vi.srt
├── auto_dub_smart_sync.py
```

---

## 🚀 4. Hướng Dẫn Cài Đặt Và Sử Dụng

### Yêu Cầu Hệ Thống
1. **FFmpeg**: Máy tính cần được cài đặt FFmpeg và thêm vào biến môi trường (Environment Variables).
2. **Cài đặt thư viện Python**:
Mở terminal và chạy lệnh sau để cài đặt các thư viện cần thiết:
```bash
pip install moviepy imageio-ffmpeg pysrt
```
*(Lưu ý: Mô hình `vieneu` cần được setup và cài đặt theo tài liệu riêng của mô hình).*

### Cách Chạy Chương Trình
**Bước 1:** Đảm bảo file video và file phụ đề `.srt` nằm chung trong một thư mục (có thể là thư mục chứa code hoặc thư mục khác).

**Bước 2:** Chạy file kịch bản chính:
```bash
python auto_dub_smart_sync.py
```

**Bước 3:** Hệ thống sẽ yêu cầu bạn nhập đường dẫn thư mục chứa video. 
* Nếu video nằm cùng thư mục với code, bạn chỉ cần nhấn **Enter**.
* Nếu video nằm ở thư mục khác, hãy copy đường dẫn thư mục paste vào và nhấn Enter.

**Bước 4:** Chờ hệ thống xử lý. Tiến trình bao gồm:
* `[SCAN]` Quét tìm file.
* Sinh âm thanh từ Text (chạy đa tiến trình).
* Thuật toán Clustering xử lý biên độ thời gian.
* FFmpeg điều chỉnh tốc độ đọc.
* Render ra file video cuối cùng.

**Kết Quả:**
Bạn sẽ nhận được một file video lồng tiếng mới có thêm hậu tố `_dubbed`.
Ví dụ: `01. Introduction_dubbed.mp4`

---
*Chúc bạn có những trải nghiệm tuyệt vời với công cụ lồng tiếng tự động này!*
