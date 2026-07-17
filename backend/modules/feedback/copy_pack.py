"""modules/feedback/copy_pack.py — centralised user-facing copy (Bahasa Indonesia, EYD V).

Every concept is expressed in three registers so the renderer can pick the
right tone depending on the audience:

    * ``humane``    — warm, empathetic, strategic ("why this matters to you").
    * ``practical`` — tactical next step ("what you can try today").
    * ``technical`` — definition + formula ("how we measure it").

**Loanword policy:** main term in Bahasa Indonesia; English in parentheses on
first occurrence where the English term is more widely cited, for example:
*"Indeks Stabilitas (Stability Index)"*, *"Bias Keyakinan Berlebih
(Overconfidence)"*.
"""

from __future__ import annotations

COPY: dict[str, dict[str, str]] = {
    # -----------------------------------------------------------------------
    # Biases
    # -----------------------------------------------------------------------
    "disposition_effect": {
        "humane": (
            "Anda cenderung cepat merealisasikan keuntungan kecil, namun "
            "bertahan pada kerugian dengan harapan akan pulih. Ini adalah "
            "pola yang sangat manusiawi — rasa takut kehilangan lebih kuat "
            "daripada kepuasan mendapatkan."
        ),
        "practical": (
            "Langkah praktis: tetapkan aturan keluar (exit rule) sebelum "
            "membeli — misalnya, jual otomatis saat kerugian mencapai 10%, "
            "dan pertahankan posisi untung selama tren positif belum patah."
        ),
        "technical": (
            "Efek Disposisi (Disposition Effect) diukur dengan DEI = PGR − PLR "
            "(Odean, 1998), di mana PGR adalah proporsi keuntungan yang "
            "direalisasikan dan PLR proporsi kerugian yang direalisasikan. "
            "Rentang nilai: [−1, 1]; nilai positif menunjukkan kecenderungan disposisi."
        ),
    },
    "overconfidence": {
        "humane": (
            "Anda terlihat yakin bahwa setiap transaksi mendekatkan Anda "
            "pada hasil terbaik. Keyakinan sehat penting, namun terlalu "
            "sering bertransaksi justru sering kali mengikis hasil investasi."
        ),
        "practical": (
            "Langkah praktis: sebelum menekan tombol Beli atau Jual, "
            "tanyakan dalam 30 detik — 'Informasi baru apa yang membenarkan "
            "transaksi ini?' Bila jawabannya tidak ada, tahan dulu satu putaran."
        ),
        "technical": (
            "Bias Keyakinan Berlebih (Overconfidence) dinyatakan sebagai "
            "OCS = sigmoid(frekuensi_trading ÷ max(rasio_kinerja, 0.01)) "
            "(Barber & Odean, 2000). Rentang [0, 1); nilai tinggi dikaitkan "
            "dengan perilaku overtrading yang merugikan return jangka panjang."
        ),
    },
    "loss_aversion": {
        "humane": (
            "Ketika harga turun, Anda memilih menunggu daripada merealisasikan "
            "kerugian — karena rasa sakit kehilangan terasa jauh lebih kuat "
            "daripada kebahagiaan dari keuntungan setara. Ini wajar, tetapi "
            "dapat menjebak modal Anda dalam posisi yang terus menurun."
        ),
        "practical": (
            "Langkah praktis: tetapkan stop-loss pada 10% saat membeli, "
            "dan tiap minggu tanyakan: 'Bila hari ini saya belum memegang "
            "saham ini, apakah saya akan membelinya di harga sekarang?' "
            "Bila jawabannya tidak, pertimbangkan untuk keluar."
        ),
        "technical": (
            "Kecenderungan Menghindari Kerugian (Loss Aversion) dinyatakan "
            "sebagai LAI = rata-rata durasi tahan posisi rugi ÷ "
            "max(rata-rata durasi tahan posisi untung, 1). Dasar teoritis: "
            "Prospect Theory (Kahneman & Tversky, 1979). LAI ≥ 2,0 "
            "dikategorikan berat."
        ),
    },

    # -----------------------------------------------------------------------
    # CDT concepts
    # -----------------------------------------------------------------------
    "stability_index": {
        "humane": (
            "Indeks Stabilitas (Stability Index) menunjukkan seberapa "
            "konsisten pola bias Anda antar-sesi. Semakin tinggi, semakin "
            "dapat diandalkan profil kognitif Anda sebagai cerminan gaya investasi."
        ),
        "practical": (
            "Bila indeks masih rendah (di bawah 0,5), pertimbangkan menambah "
            "sesi simulasi agar profil Anda lebih representatif sebelum "
            "membuat kesimpulan perilaku."
        ),
        "technical": (
            "Indeks Stabilitas dihitung sebagai 1 − CV, di mana CV adalah "
            "koefisien variasi (coefficient of variation) vektor intensitas "
            "bias antar-sesi dalam jendela CDT_STABILITY_WINDOW."
        ),
    },
    "risk_preference": {
        "humane": (
            "Preferensi Risiko mencerminkan seberapa sering Anda memilih "
            "saham bervolatilitas tinggi dibandingkan saham yang relatif stabil."
        ),
        "practical": (
            "Bila preferensi Anda ternyata jauh lebih agresif dari yang "
            "Anda bayangkan, pertimbangkan untuk menyeimbangkan portofolio "
            "dengan saham berkapitalisasi besar dan arus kas positif."
        ),
        "technical": (
            "Preferensi Risiko diperbarui menggunakan *Exponential Moving "
            "Average* (EMA) dengan bobot BETA pada observasi terbaru; "
            "hanya saham di kelas volatilitas tinggi yang berkontribusi "
            "terhadap observed_risk."
        ),
    },
    "cdt_ema": {
        "humane": (
            "Profil *Cognitive Digital Twin* (CDT) tidak langsung berubah "
            "pada satu sesi; ia belajar bertahap dari seluruh riwayat Anda, "
            "dengan bobot lebih besar pada pengalaman terbaru."
        ),
        "practical": (
            "Tambahkan sesi secara rutin — semakin banyak data, semakin "
            "akurat profil Anda mencerminkan kebiasaan nyata, bukan "
            "fluktuasi satu hari."
        ),
        "technical": (
            "BiasIntensity(t) = α · metric(t) + (1 − α) · BiasIntensity(t−1), "
            "dengan ALPHA = 0.3 sebagai dasar dan ALPHA_MAX = 0.45 untuk "
            "sesi dengan aktivitas tinggi."
        ),
    },
}


def get(concept: str, register: str = "humane") -> str:
    """Retrieve a copy snippet. Raises KeyError on unknown concept/register."""
    if concept not in COPY:
        raise KeyError(f"unknown copy concept: {concept!r}")
    if register not in COPY[concept]:
        raise KeyError(
            f"unknown register {register!r} for concept {concept!r}; "
            f"choose one of {list(COPY[concept])}"
        )
    return COPY[concept][register]
