/**
 * lib/glossary.ts — single source of truth for the plain-language explanations
 * of every bias term and index the app shows a general-audience user.
 *
 * Used in two places so the wording never drifts:
 *  - <Term> inline tooltips on /hasil and /profil (the `short` text), and
 *  - the /metodologi page (both `short` and `long`).
 *
 * Register: an experienced investing mentor — warm, plain, no jargon dumps.
 * These are educational summaries of the concepts; they are NOT the scientific
 * instrument text and carry no parity constraint.
 */

export interface GlossaryEntry {
  /** Heading shown on the methodology page and as the tooltip title. */
  label: string;
  /** One–two sentences for the inline tooltip. */
  short: string;
  /** Fuller explanation for the methodology page. */
  long: string;
}

export const GLOSSARY: Record<string, GlossaryEntry> = {
  disposition: {
    label: "Efek Disposisi",
    short:
      "Kecenderungan menjual saham yang sedang untung terlalu cepat, sekaligus menahan yang rugi terlalu lama.",
    long:
      "Efek disposisi adalah pola menjual posisi yang untung terlalu dini dan " +
      "menahan posisi yang rugi terlalu lama, sering karena ingin “mengunci” " +
      "keuntungan dan menghindari mengakui kerugian. Dalam jangka panjang pola " +
      "ini cenderung memperkecil keuntungan dan memperbesar kerugian. Aplikasi " +
      "mengukurnya lewat indeks DEI, yaitu selisih antara kecenderungan " +
      "merealisasi keuntungan dan merealisasi kerugian.",
  },
  overconfidence: {
    label: "Keyakinan Berlebih",
    short:
      "Keyakinan yang berlebihan pada penilaian sendiri, sering terlihat dari transaksi yang terlalu sering.",
    long:
      "Keyakinan berlebih (overconfidence) adalah kecenderungan menilai " +
      "kemampuan atau informasi diri lebih tinggi daripada kenyataannya. Pada " +
      "aktivitas investasi, ini kerap muncul sebagai frekuensi transaksi yang " +
      "tinggi — merasa mampu “mengalahkan pasar” secara konsisten. Aplikasi " +
      "membaca sinyalnya lewat skor OCS berdasarkan intensitas transaksi Anda.",
  },
  loss_aversion: {
    label: "Menghindari Kerugian",
    short:
      "Rasa sakit dari rugi terasa lebih besar daripada senang dari untung yang setara, sehingga keputusan condong menghindari kerugian.",
    long:
      "Menghindari kerugian (loss aversion) menggambarkan bahwa rasa sakit " +
      "kehilangan biasanya terasa lebih kuat daripada kesenangan dari " +
      "keuntungan dengan nilai yang sama. Akibatnya seseorang bisa mengambil " +
      "keputusan yang kurang optimal demi menghindari kerugian, misalnya " +
      "menahan posisi rugi terlalu lama. Aplikasi mengukurnya lewat indeks LAI.",
  },
  cdt: {
    label: "Cognitive Digital Twin (CDT)",
    short:
      "Representasi digital dari pola pengambilan keputusan Anda yang diperbarui sedikit demi sedikit setiap sesi.",
    long:
      "Cognitive Digital Twin (CDT) adalah “kembaran digital” dari kebiasaan " +
      "pengambilan keputusan Anda. Setiap sesi simulasi memperbarui profil ini " +
      "sedikit demi sedikit menggunakan rata-rata bergerak (EMA), sehingga " +
      "arah profil mencerminkan kebiasaan yang menetap, bukan hasil satu sesi " +
      "yang kebetulan. Dari sinilah peta bias dan perjalanan profil Anda dibaca.",
  },
  stability: {
    label: "Indeks Konsistensi",
    short:
      "Seberapa konsisten pola bias Anda dari satu sesi ke sesi berikutnya. Makin tinggi, makin stabil polanya.",
    long:
      "Indeks konsistensi (stabilitas) mengukur seberapa mirip pola bias Anda " +
      "antar sesi. Nilai yang tinggi berarti kecenderungan Anda relatif " +
      "menetap; nilai rendah berarti pola masih berubah-ubah, yang wajar pada " +
      "sesi-sesi awal ketika datanya belum banyak.",
  },
  interaction: {
    label: "Keterkaitan Antar-Bias",
    short:
      "Ukuran apakah dua bias cenderung muncul bersamaan. Nilainya −1 sampai +1; makin jauh dari nol, makin erat kaitannya.",
    long:
      "Keterkaitan antar-bias mengukur apakah dua kecenderungan muncul " +
      "bersamaan selama beberapa sesi terakhir, dinyatakan sebagai korelasi " +
      "dari −1 sampai +1. Nilai mendekati +1 berarti keduanya naik-turun " +
      "bersama; mendekati −1 berarti saling berlawanan; mendekati nol berarti " +
      "tidak terkait. Aplikasi menandai keterkaitan yang erat (di atas 0,65) " +
      "karena kombinasi bias sering berdampak lebih besar daripada masing-masing sendiri.",
  },
};
