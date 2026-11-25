# Video Trung → Việt với Hoài My

Mở thư mục vừa giải nén trong VS Code. Mở Terminal PowerShell và chạy từng dòng.
Dùng Python 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Chép MP4 và SRT vào thư mục. Với phụ đề Việt có sẵn:

```powershell
.\.venv\Scripts\python.exe video_viet.py "tap8.mp4" --srt-viet "tap8.vi.srt"
```

Với phụ đề Trung, thay bằng `--srt-trung "tap8.zh.srt"`. Nếu chỉ có chữ
Trung dính trên hình, cài Tesseract cho Windows với dữ liệu tiếng Trung
giản thể (chi_sim), rồi chạy:

```powershell
.\.venv\Scripts\python.exe video_viet.py "tap8.mp4" --ocr --tesseract "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

OCR đọc dải dưới của nguồn ở 2 khung hình mỗi giây. Video dài cần thời gian
và dung lượng tạm để lưu khung OCR. Phụ đề OCR lưu dưới tên tap8.ocr.zh.srt.
Thêm --ocr-only để chỉ trích SRT tiếng Trung. Nên soát file này trước khi
dùng --srt-trung vì OCR có thể đọc nhầm chữ, nhất là khi chữ chồng lên nhau. Bước dịch
gửi văn bản tới Google Translate và bước đọc gửi phụ đề Việt tới Edge TTS.
Nếu đã có bản dịch, --srt-viet bỏ qua Google Translate. Các câu đã đọc được
lưu để chạy tiếp nếu dịch vụ gián đoạn. Câu đọc dài hơn mốc phụ đề có thể
khiến câu kế tiếp bắt đầu muộn.

Đầu ra mặc định tap8.hoai-my.mp4. Giọng Hoài My 1,25×, âm gốc 15%, crop
6% phía trên và 12% phía dưới trước khi gắn phụ đề Việt. Có thể đổi bằng
--crop-top 8 --crop-bottom 14 --am-goc 20. Dùng --output "tap8-ban-2.mp4"
để giữ các bản xuất riêng. Dòng [Nghe không rõ] được bỏ khỏi cả sub và giọng đọc.
