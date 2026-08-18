# Quy tắc gán nhãn MathLens v0

Tài liệu này dùng khi con người gán nhãn dữ liệu, để hai người gán độc lập cho ra
cùng một kết quả. Đây cũng là phần nên xin thầy/cô rà soát sớm nhất.

## Quy trình cho một mẫu

1. Đọc lời giải từ trên xuống, dừng ở **bước đầu tiên không tương đương** với bước
   ngay trước nó. Ghi số thứ tự bước đó vào `first_incorrect_step` (đánh số từ 1).
2. Nếu mọi bước đều hợp lệ, để `first_incorrect_step` và `misconception_id` là `null`.
3. Chỉ gán **một** nhãn cho bước sai đầu tiên. Các bước sai phía sau không gán nhãn,
   vì chúng thường là hệ quả của bước sai đầu.

## Ranh giới giữa các nhãn dễ nhầm

**Lỗi tư duy hay lỗi tính toán?**
Đặt câu hỏi: nếu chỉ sửa lại một con số, bước đó có đúng không?

- Có, ví dụ `2x=6` thành `x=4`: quy tắc đúng, chỉ sai số học. Nhãn `ALG-CALC-01`.
- Không, ví dụ `2x+4=10` thành `x+4=5`: quy tắc chia hai vế bị áp dụng thiếu.
  Nhãn `ALG-EQ-03`.

**ALG-DIST-01 hay ALG-FRAC-01?**
Nếu thừa số bên ngoài là phép nhân, dùng `ALG-DIST-01`. Nếu là phép chia,
ví dụ `(3x+6)/3` thành `x+6`, dùng `ALG-FRAC-01`.

**ALG-SIGN-01 hay ALG-SIGN-02?**
`ALG-SIGN-01` là chuyển vế mà quên đổi dấu. `ALG-SIGN-02` là nhân hoặc chia hai vế
cho số âm nhưng chỉ đổi dấu một phần các hạng tử.

**ALG-EXP-01 hay ALG-POW-04?**
Số mũ bằng 2 thì dùng `ALG-EXP-01` hoặc `ALG-EXP-02` tùy dấu bên trong ngoặc.
Số mũ từ 3 trở lên dùng `ALG-POW-04`.

**ALG-QUAD-01 hay ALG-EQ-01?**
Mất nghiệm do chỉ lấy căn dương từ `x^2=k` là `ALG-QUAD-01`.
Mất nghiệm do chia hai vế cho biểu thức chứa ẩn là `ALG-EQ-01`.

## Khi không chắc

Ghi nhãn `ALG-UNK-00` và mô tả bằng lời vào trường `note` thay vì đoán. Các mẫu
`ALG-UNK-00` chính là nguồn để mở rộng taxonomy ở vòng sau.

## Kiểm tra độ đồng thuận

Với mỗi 50 mẫu mới, nên có ít nhất 20 mẫu được hai người gán độc lập. Ghi lại tỷ lệ
trùng khớp và danh sách các cặp nhãn hay bị nhầm lẫn. Nếu một cặp nhãn liên tục bị
nhầm, nên gộp lại hoặc viết lại định nghĩa, chứ không nên giữ nguyên rồi đổ lỗi cho
người gán.
