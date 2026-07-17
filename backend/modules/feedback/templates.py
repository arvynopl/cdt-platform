"""
modules/feedback/templates.py — Bahasa Indonesia feedback template library.

9 template pairs: 3 biases × 3 severity levels (mild / moderate / severe).
Each entry contains:
    explanation   — Describes the detected bias and its magnitude.
    recommendation — Actionable advice to mitigate the bias.

Slot placeholders (Python .format() style):
    {dei}           Disposition Effect Index value
    {pgr}           Proportion of Gains Realized
    {plr}           Proportion of Losses Realized
    {ocs}           Overconfidence Score value
    {lai}           Loss Aversion Index value
    {trade_count}   Total buy+sell trades in the session
    {win_count}     Number of realized gains
    {loss_count}    Number of realized losses
    {counterfactual_text}  (severe templates only)
"""

from __future__ import annotations

TEMPLATES: dict[str, dict[str, dict[str, str]]] = {

    # -----------------------------------------------------------------------
    # Disposition Effect
    # -----------------------------------------------------------------------
    "disposition_effect": {
        "mild": {
            "explanation": (
                "Pada sesi ini kamu menunjukkan kecenderungan ringan untuk merealisasi "
                "keuntungan terlalu cepat. Indeks Efek Disposisi (DEI) kamu adalah "
                "{dei:.2f}, dengan rasio realisasi keuntungan (PGR) sebesar {pgr:.2f} "
                "dan rasio realisasi kerugian (PLR) sebesar {plr:.2f}. Ini berarti kamu "
                "cenderung sedikit lebih cepat menjual saham yang untung dibanding yang rugi."
            ),
            "recommendation": (
                "Cobalah untuk menetapkan target harga jual sebelum membeli saham. "
                "Pertimbangkan untuk menahan posisi yang menguntungkan sedikit lebih lama "
                "agar keuntungan dapat berkembang. Ingat: menjual terlalu dini bisa membuat "
                "kamu kehilangan potensi keuntungan yang lebih besar."
            ),
        },
        "moderate": {
            "explanation": (
                "Kamu menunjukkan efek disposisi yang cukup signifikan pada sesi ini. "
                "DEI kamu adalah {dei:.2f} — kamu merealisasi {win_count} keuntungan "
                "(PGR = {pgr:.2f}) tetapi hanya {loss_count} kerugian (PLR = {plr:.2f}). "
                "Pola ini menunjukkan kamu cenderung 'mengunci' keuntungan kecil sambil "
                "membiarkan posisi merugi terus menggerogoti portofoliomu."
            ),
            "recommendation": (
                "Terapkan strategi stop-loss yang tegas: tentukan batas kerugian maksimal "
                "(misalnya 5–10%) sebelum masuk posisi, dan patuhi aturan tersebut. "
                "Di sisi lain, gunakan strategi trailing stop untuk membiarkan keuntungan "
                "tumbuh sebelum keluar dari posisi yang bagus."
            ),
        },
        "severe": {
            "explanation": (
                "Efek disposisi yang kamu tunjukkan sangat kuat (DEI = {dei:.2f}). "
                "Kamu merealisasi hampir semua keuntungan (PGR = {pgr:.2f}) tetapi "
                "sangat jarang menjual posisi yang merugi (PLR = {plr:.2f}). "
                "Pola ini secara signifikan menurunkan performa portofoliomu secara jangka panjang. "
                "{counterfactual_text}"
            ),
            "recommendation": (
                "Lakukan evaluasi menyeluruh terhadap setiap posisi yang merugi: apakah "
                "alasan fundamentalmu untuk membeli masih valid? Jika tidak, pertimbangkan "
                "untuk cut loss. Setiap minggu, tinjau semua posisi merugi dan tanyakan: "
                "'Apakah saya akan membeli saham ini hari ini di harga ini?' Jika jawabannya "
                "tidak, pertimbangkan untuk keluar dari posisi tersebut."
            ),
        },
    },

    # -----------------------------------------------------------------------
    # Overconfidence
    # -----------------------------------------------------------------------
    "overconfidence": {
        "mild": {
            "explanation": (
                "Tingkat aktivitas trading kamu sedikit di atas rata-rata dengan skor "
                "kepercayaan diri berlebih (OCS) sebesar {ocs:.2f}. Dalam {trade_count} "
                "transaksi, performa portofoliomu masih terjaga. Namun perlu diperhatikan "
                "bahwa frekuensi trading yang tinggi meningkatkan biaya transaksi."
            ),
            "recommendation": (
                "Sebelum setiap transaksi, luangkan waktu 30 detik untuk menanyakan: "
                "'Apa informasi baru yang mendorong saya untuk trading sekarang?' "
                "Jika jawabannya tidak ada, pertimbangkan untuk menahan."
            ),
        },
        "moderate": {
            "explanation": (
                "Kamu melakukan {trade_count} transaksi dalam 14 putaran dengan OCS = {ocs:.2f}. "
                "Pola trading aktif ini, dikombinasikan dengan performa portofolio, menunjukkan "
                "kamu mungkin terlalu percaya diri dengan kemampuan membaca pergerakan pasar "
                "jangka pendek. Penelitian menunjukkan investor aktif sering underperform pasar."
            ),
            "recommendation": (
                "Coba terapkan aturan 'tunggu satu putaran': setelah ingin trading, tunggu "
                "satu putaran lagi dan evaluasi ulang apakah keputusanmu masih valid. "
                "Catat alasan setiap transaksi dan evaluasi setelah sesi selesai."
            ),
        },
        "severe": {
            "explanation": (
                "Kamu menunjukkan overconfidence yang sangat tinggi (OCS = {ocs:.2f}). "
                "Dengan {trade_count} transaksi dalam sesi ini, frekuensi trading kamu jauh "
                "melebihi rata-rata optimal. Penelitian Barber & Odean (2000) menunjukkan "
                "investor paling aktif menghasilkan return 6.5% lebih rendah per tahun. "
                "{counterfactual_text}"
            ),
            "recommendation": (
                "Tetapkan batas maksimal transaksi per sesi (misalnya 6 transaksi untuk 14 putaran). "
                "Sebelum setiap keputusan, tulis alasanmu di atas kertas — jika tidak bisa "
                "mengartikulasikan alasan yang kuat, jangan trading. Fokus pada kualitas "
                "keputusan, bukan kuantitas transaksi."
            ),
        },
    },

    # -----------------------------------------------------------------------
    # Loss Aversion
    # -----------------------------------------------------------------------
    "loss_aversion": {
        "mild": {
            "explanation": (
                "Kamu sedikit lebih lama menahan saham yang merugi dibanding yang untung "
                "(LAI = {lai:.2f}). Ini adalah bias yang umum terjadi dan masih dalam "
                "batas wajar. Kahneman & Tversky (1979) menemukan bahwa rasa sakit dari "
                "kerugian dua kali lebih kuat dari kesenangan atas keuntungan setara."
            ),
            "recommendation": (
                "Saat membeli saham, tentukan level stop-loss di awal dan patuhi keputusan "
                "tersebut. Ini membantu mengambil keputusan secara objektif sebelum terlibat "
                "secara emosional dengan posisi yang sedang merugi."
            ),
        },
        "moderate": {
            "explanation": (
                "Kamu menahan posisi merugi rata-rata {lai:.1f}x lebih lama dari posisi "
                "yang menguntungkan (LAI = {lai:.2f}). Pola ini menunjukkan kamu cenderung "
                "menghindari 'mengunci' kerugian, berharap harga akan kembali naik — "
                "sebuah bias yang bisa sangat merugikan dalam kondisi pasar yang turun."
            ),
            "recommendation": (
                "Praktikkan reframing: kerugian yang belum direalisasi tetap adalah kerugian "
                "nyata dalam nilai portofoliomu. Terapkan aturan: jika saham turun >8% dari "
                "harga beli, review apakah thesis investasimu masih valid. Jika tidak, keluar."
            ),
        },
        "severe": {
            "explanation": (
                "Loss aversion yang sangat kuat terdeteksi (LAI = {lai:.2f}). Kamu menahan "
                "posisi merugi hampir {lai:.1f}x lebih lama dari posisi untung. Ini adalah "
                "salah satu bias paling merusak dalam investasi jangka panjang karena modal "
                "terjebak dalam posisi yang terus menurun nilainya. "
                "{counterfactual_text}"
            ),
            "recommendation": (
                "Implementasikan sistem stop-loss yang tidak bisa diabaikan: tetapkan alert "
                "otomatis saat harga turun 10% dari harga beli. Ingat bahwa cut loss bukan "
                "'kalah' — itu adalah manajemen risiko yang bijak. Modal yang diselamatkan "
                "dari posisi rugi bisa digunakan untuk peluang investasi yang lebih baik."
            ),
        },
    },
}
