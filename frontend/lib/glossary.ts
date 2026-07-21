/**
 * lib/glossary.ts — single source of truth for the plain-language explanations
 * of every bias term and index the app shows a general-audience user.
 *
 * Used in two places so the wording never drifts:
 *  - <Term> inline tooltips on /hasil and /profil (the `short` text), and
 *  - the /metodologi page (both `short` and `long`).
 *
 * House style: short sentences, one idea each. No em-dashes, no semicolons,
 * no ampersands. Write like an experienced mentor talking, not like a paper.
 */

export interface GlossaryEntry {
  /** Heading shown on the methodology page and as the tooltip title. */
  label: string;
  /** One or two short sentences for the inline tooltip. */
  short: string;
  /** Fuller explanation for the methodology page. */
  long: string;
}

export const GLOSSARY: Record<string, GlossaryEntry> = {
  disposition: {
    label: "Efek Disposisi",
    short:
      "Kecenderungan menjual saham yang untung terlalu cepat. Saham yang rugi justru ditahan terlalu lama.",
    long:
      "Efek disposisi muncul saat Anda buru-buru menjual posisi yang untung, " +
      "tetapi menahan posisi yang rugi. Dorongannya masuk akal. Anda ingin " +
      "mengunci keuntungan dan menunda rasa kecewa. Dalam jangka panjang pola " +
      "ini memangkas keuntungan dan membiarkan kerugian membesar. Aplikasi " +
      "mengukurnya lewat indeks DEI, yaitu selisih antara kecenderungan " +
      "merealisasi keuntungan dan merealisasi kerugian.",
  },
  overconfidence: {
    label: "Keyakinan Berlebih",
    short:
      "Menilai kemampuan sendiri lebih tinggi dari kenyataan. Tandanya sering terlihat dari transaksi yang terlalu sering.",
    long:
      "Keyakinan berlebih membuat seseorang merasa lebih tahu daripada pasar. " +
      "Pada investasi, tandanya biasanya frekuensi transaksi yang tinggi. " +
      "Setiap transaksi terasa seperti peluang, padahal sebagian hanya menambah " +
      "biaya dan risiko. Aplikasi membaca sinyalnya lewat skor OCS berdasarkan " +
      "intensitas transaksi Anda.",
  },
  loss_aversion: {
    label: "Menghindari Kerugian",
    short:
      "Rasa sakit karena rugi terasa lebih besar daripada senang karena untung dengan nilai sama.",
    long:
      "Kehilangan uang terasa lebih menyakitkan daripada nikmatnya untung " +
      "dengan nilai yang sama. Akibatnya keputusan sering condong menghindari " +
      "kerugian, misalnya menahan posisi rugi jauh lebih lama daripada " +
      "seharusnya. Aplikasi mengukurnya lewat indeks LAI.",
  },
  cdt: {
    label: "Cognitive Digital Twin (CDT)",
    short:
      "Kembaran digital dari kebiasaan Anda mengambil keputusan. Diperbarui sedikit demi sedikit setiap sesi.",
    long:
      "Cognitive Digital Twin adalah gambaran kebiasaan Anda dalam mengambil " +
      "keputusan. Setiap sesi menggeser profil ini sedikit saja, memakai " +
      "rata-rata bergerak. Cara itu membuat arah profil mencerminkan kebiasaan " +
      "yang menetap, bukan satu sesi yang kebetulan bagus atau buruk. Dari " +
      "sinilah peta bias dan perjalanan profil Anda dibaca.",
  },
  stability: {
    label: "Indeks Konsistensi",
    short:
      "Seberapa mirip pola Anda dari sesi ke sesi. Makin tinggi, makin menetap polanya.",
    long:
      "Indeks konsistensi mengukur seberapa mirip pola bias Anda antar sesi. " +
      "Nilai tinggi berarti kecenderungan Anda sudah menetap. Nilai rendah " +
      "berarti pola masih berubah-ubah. Pada sesi-sesi awal nilai rendah itu " +
      "wajar karena datanya memang belum banyak.",
  },
  interaction: {
    label: "Keterkaitan Antar-Bias",
    short:
      "Mengukur apakah dua bias muncul bersamaan. Nilainya −1 sampai +1. Makin jauh dari nol, makin erat kaitannya.",
    long:
      "Keterkaitan antar-bias melihat apakah dua kecenderungan Anda bergerak " +
      "bersamaan selama beberapa sesi terakhir. Nilainya berkisar dari −1 " +
      "sampai +1. Mendekati +1 berarti keduanya naik dan turun bersama. " +
      "Mendekati −1 berarti keduanya berlawanan arah. Mendekati nol berarti " +
      "tidak berkaitan. Aplikasi menandai keterkaitan yang erat di atas 0,65 " +
      "karena kombinasi bias sering berdampak lebih besar daripada satu bias " +
      "yang berdiri sendiri.",
  },
};
