"""Internal Streamlit view, kept as a debugging tool for the engine.

Run: streamlit run app/streamlit_app.py

The public interface is the web app in web/. This one shows Vietnamese text
only and exists so engine changes can be eyeballed without the frontend.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import feedback_engine, storage  # noqa: E402
from engine.step_checker import (  # noqa: E402
    STATUS_AFTER_ERROR,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_PARSE_ERROR,
    analyze,
)

PROBLEMS_PATH = ROOT / "data" / "problems.csv"

st.set_page_config(page_title="MathLens", page_icon="🔍", layout="wide")


@st.cache_data
def load_problems() -> pd.DataFrame:
    return pd.read_csv(PROBLEMS_PATH)


@st.cache_data
def taxonomy_frame() -> pd.DataFrame:
    tax = feedback_engine.load_taxonomy()
    return pd.DataFrame([
        {
            "Mã": m.id,
            "Nhóm": m.group,
            "Tên lỗi": m.name_vi,
            "Ví dụ sai": m.wrong_example,
            "Ví dụ đúng": m.correct_example,
        }
        for m in tax.values()
    ])


def init_state() -> None:
    st.session_state.setdefault("session_id", storage.new_session_id())
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("feedback", None)
    st.session_state.setdefault("attempt_id", None)
    st.session_state.setdefault("diagnostic_state", None)


ICONS = {
    STATUS_OK: "✅",
    STATUS_ERROR: "❌",
    STATUS_PARSE_ERROR: "⚠️",
    STATUS_AFTER_ERROR: "➖",
}

NOTES = {
    STATUS_OK: "Hợp lệ",
    STATUS_ERROR: "Không tương đương với bước trước",
    STATUS_PARSE_ERROR: "Không đọc được",
    STATUS_AFTER_ERROR: "Sau bước sai đầu tiên",
}

RELATION_NOTE = {
    "lost_roots": "Bước này làm mất nghiệm so với bước trước.",
    "extra_roots": "Bước này sinh thêm nghiệm không có ở bước trước.",
    "not_equivalent": "Hai bước không tương đương.",
}


def render_solve_tab() -> None:
    problems = load_problems()
    left, right = st.columns([1, 1])

    with left:
        st.subheader("1. Chọn bài")
        labels = ["(Tự nhập đề bài)"] + [
            f"{r.problem_id} · {r.question}" for r in problems.itertuples()
        ]
        choice = st.selectbox("Đề bài", labels, label_visibility="collapsed")

        if choice == labels[0]:
            question = st.text_input("Đề bài tự nhập", "")
            problem_id, topic = "", ""
        else:
            row = problems.iloc[labels.index(choice) - 1]
            question = row["question"]
            problem_id, topic = row["problem_id"], row["topic"]
            st.info(question)

        st.subheader("2. Nhập lời giải theo từng bước")
        st.caption(
            "Mỗi dòng là một bước. Dùng ^ cho lũy thừa, sqrt() cho căn. "
            "Ví dụ: 3(x+2)=12 rồi xuống dòng 3x+6=12."
        )
        solution = st.text_area(
            "Lời giải", height=200, label_visibility="collapsed",
            placeholder="3(x+2)=12\n3x+2=12\n3x=10",
        )
        analyse = st.button("Phân tích lời giải", type="primary", width="stretch")

    if analyse:
        if not solution.strip():
            st.warning("Hãy nhập ít nhất một bước.")
        else:
            result = analyze(solution)
            st.session_state.result = result
            st.session_state.feedback = feedback_engine.build_feedback(result)
            st.session_state.attempt_id = storage.log_attempt(
                st.session_state.session_id, solution, result,
                problem_id=problem_id, topic=topic,
            )
            st.session_state.diagnostic_state = None

    with right:
        st.subheader("3. Kết quả phân tích")
        result = st.session_state.result
        if result is None:
            st.caption("Chưa có lời giải nào được phân tích.")
            return

        rows = []
        for s in result.steps:
            rows.append({
                "": ICONS.get(s.status, ""),
                "Bước": s.index + 1,
                "Nội dung": s.pretty,
                "Nhận xét": s.note or NOTES.get(s.status, ""),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        fb = st.session_state.feedback
        if fb["status"] == "correct":
            st.success(fb["headline"]["vi"])
            st.caption(fb["detail"]["vi"])
            return

        st.error(fb["headline"]["vi"])
        bad = result.steps[result.first_error_index]
        st.caption(RELATION_NOTE.get(bad.relation, ""))

        mis = fb["misconception"]
        if mis is not None:
            st.markdown(f"**Dạng hiểu nhầm:** {mis.name_vi}  ·  `{mis.id}`")
            st.write(fb["detail"]["vi"])
            if mis.wrong_example:
                c1, c2 = st.columns(2)
                c1.markdown(f"Sai: `{mis.wrong_example}`")
                c2.markdown(f"Đúng: `{mis.correct_example}`")

        with st.expander("Vì sao hệ thống kết luận như vậy (dành cho giáo viên)"):
            for m in result.ranked:
                st.write(f"- `{m.misconception_id}` · độ tin cậy {m.confidence:.2f} · {m.evidence}")

        render_diagnostic(fb)


def render_diagnostic(fb: dict) -> None:
    if not fb["diagnostic_question"]["vi"]:
        return
    st.divider()
    st.subheader("4. Câu hỏi chẩn đoán")
    st.write(fb["diagnostic_question"]["vi"])
    answer = st.text_input("Trả lời", key="diagnostic_answer")
    if st.button("Kiểm tra"):
        ok = feedback_engine.check_diagnostic(answer, fb["diagnostic_answer"])
        st.session_state.diagnostic_state = ok
        storage.set_diagnostic_result(st.session_state.attempt_id, ok)

    state = st.session_state.diagnostic_state
    if state is True:
        st.success("Đúng. Bạn đã áp dụng đúng quy tắc ở dạng bài tương tự.")
    elif state is False:
        st.warning("Chưa đúng. Hãy đọc lại phần giải thích rồi thử lại.")
    elif state is None and answer:
        st.info("Chưa chấm được câu trả lời này.")


def render_profile_tab() -> None:
    st.subheader("Hồ sơ phiên làm bài")
    data = storage.profile(st.session_state.session_id)
    c1, c2, c3 = st.columns(3)
    c1.metric("Lượt phân tích", data["total_attempts"])
    c2.metric("Lời giải không có lỗi", data["clean_attempts"])
    wrong = data["total_attempts"] - data["clean_attempts"]
    c3.metric("Lời giải có lỗi", wrong)

    if not data["by_misconception"]:
        st.caption("Chưa có dữ liệu lỗi trong phiên này.")
        return

    tax = feedback_engine.load_taxonomy()
    rows = []
    for item in data["by_misconception"]:
        mis = tax.get(item["id"])
        rows.append({
            "Mã": item["id"],
            "Dạng hiểu nhầm": mis.name_vi if mis else item["id"],
            "Số lần": item["count"],
            "Đã trả lời chẩn đoán": item["answered"],
            "Trả lời đúng": item["fixed"],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        "Cột chẩn đoán cho biết sau khi nhận phản hồi, học sinh có làm đúng "
        "câu hỏi cùng khái niệm hay không. Đây là chỉ số chính để đánh giá "
        "hiệu quả của phản hồi."
    )


def render_taxonomy_tab() -> None:
    st.subheader("Taxonomy lỗi toán học v0")
    st.dataframe(taxonomy_frame(), hide_index=True, width="stretch")
    st.caption(
        "Mỗi nhãn có định nghĩa, ví dụ sai, ví dụ đúng và một câu hỏi chẩn đoán. "
        "Taxonomy là dữ liệu, không phải code, nên giáo viên có thể sửa trực tiếp "
        "trong data/misconceptions.csv."
    )


def render_about_tab() -> None:
    st.subheader("Hệ thống hoạt động thế nào")
    st.markdown(
        """
1. **Parser** chuẩn hóa cách nhập của học sinh và tách từng bước.
2. **Symbolic checker** kiểm tra hai bước liên tiếp có tương đương hay không.
   Với phương trình, hệ thống so sánh tập nghiệm nên phát hiện được cả trường
   hợp mất nghiệm hoặc sinh nghiệm ngoại lai.
3. **Rule engine** mô phỏng từng lỗi tư duy: với bước đúng trước đó, mỗi luật
   sinh ra kết quả mà học sinh *sẽ* viết nếu mắc đúng lỗi đó. Luật nào cho ra
   đúng thứ học sinh viết thì được coi là khớp.
4. **Lớp ML** chỉ được gọi khi không luật nào khớp, và chỉ để xếp hạng gợi ý.
   ML không bao giờ quyết định một bước là đúng hay sai.
5. **Feedback** nêu bước sai đầu tiên, tên dạng hiểu nhầm và một câu hỏi chẩn
   đoán cùng khái niệm, không đưa ngay lời giải đầy đủ.
        """
    )
    st.subheader("Giới hạn đã biết của phiên bản này")
    st.markdown(
        """
- Chỉ xử lý Đại số ở phạm vi đã khai báo trong kế hoạch, chưa có hình học và OCR.
- Parser yêu cầu mỗi dòng là một bước và mỗi dòng nhiều nhất một dấu bằng.
- Kết quả đánh giá hiện có chạy trên seed set do chính người xây luật viết ra,
  nên chưa phải benchmark khách quan. Cần một test set độc lập do giáo viên
  hoặc học sinh khác tạo.
- Khi một bước sai có thể giải thích bằng nhiều lỗi khác nhau, hệ thống chọn
  nhãn có độ tin cậy cao nhất và hiển thị các nhãn còn lại trong phần bằng chứng.
        """
    )


def main() -> None:
    init_state()
    st.title("MathLens")
    st.caption("Hệ thống phát hiện lỗi tư duy trong lời giải Đại số của học sinh")

    with st.sidebar:
        st.markdown("**Phiên làm việc**")
        st.code(st.session_state.session_id)
        st.caption(
            "Dữ liệu được lưu ẩn danh theo mã phiên, không lưu họ tên hay "
            "thông tin cá nhân."
        )
        if st.button("Bắt đầu phiên mới"):
            for key in ("session_id", "result", "feedback", "attempt_id", "diagnostic_state"):
                st.session_state.pop(key, None)
            st.rerun()

    tabs = st.tabs(["Luyện tập", "Hồ sơ", "Taxonomy", "Về hệ thống"])
    with tabs[0]:
        render_solve_tab()
    with tabs[1]:
        render_profile_tab()
    with tabs[2]:
        render_taxonomy_tab()
    with tabs[3]:
        render_about_tab()


if __name__ == "__main__":
    main()
