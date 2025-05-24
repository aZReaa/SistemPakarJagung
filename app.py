from flask import Flask, render_template, request, flash, jsonify, redirect
from functools import lru_cache
import json
import logging
import os
from datetime import datetime

# Import konfigurasi
from config import (
    DEBUG, KNOWLEDGE_BASE_PATH, LOG_FORMAT, LOG_LEVEL, 
    LOG_FILE, CACHE_TIMEOUT
)

# Konfigurasi logging
logging.basicConfig(
    filename=LOG_FILE,
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Diperlukan untuk flash messages

# --- Cache Management ---
cache = {}
last_kb_load_time = None

# --- Helper Functions ---

def should_reload_kb():
    """Memeriksa apakah knowledge base perlu dimuat ulang."""
    global last_kb_load_time
    
    if last_kb_load_time is None:
        return True
        
    # Reload jika file berubah setelah loading terakhir
    try:
        kb_file_mtime = os.path.getmtime(KNOWLEDGE_BASE_PATH)
        if kb_file_mtime > last_kb_load_time:
            logger.info(f"File knowledge base berubah. Memuat ulang.")
            return True
    except Exception as e:
        logger.warning(f"Gagal memeriksa waktu modifikasi file: {e}")
    
    # Reload jika lebih dari CACHE_TIMEOUT
    time_diff = datetime.now().timestamp() - last_kb_load_time
    if time_diff > CACHE_TIMEOUT:
        logger.info(f"Cache kadaluarsa ({time_diff:.1f}s). Memuat ulang knowledge base.")
        return True
        
    return False

def load_knowledge_base(filepath=KNOWLEDGE_BASE_PATH, force_reload=False):
    """
    Memuat basis pengetahuan dari file JSON dengan caching.
    
    Args:
        filepath (str): Path ke file knowledge base
        force_reload (bool): Paksa reload walaupun cache masih valid
        
    Returns:
        dict: Knowledge base yang telah dimuat
    """
    global KNOWLEDGE_BASE, last_kb_load_time
    
    if not force_reload and not should_reload_kb():
        logger.debug("Menggunakan knowledge base dari cache.")
        return KNOWLEDGE_BASE
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            KNOWLEDGE_BASE = json.load(f)
        last_kb_load_time = datetime.now().timestamp()
        logger.info("Basis Pengetahuan Berhasil Dimuat.")
        return KNOWLEDGE_BASE
    except FileNotFoundError:
        logger.error(f"File {filepath} tidak ditemukan.")
        KNOWLEDGE_BASE = {}
    except json.JSONDecodeError:
        logger.error(f"File {filepath} tidak dalam format JSON yang valid.")
        KNOWLEDGE_BASE = {}
    except Exception as e:
        logger.error(f"Terjadi kesalahan saat memuat basis pengetahuan: {e}")
        KNOWLEDGE_BASE = {}
    
    last_kb_load_time = datetime.now().timestamp()
    return KNOWLEDGE_BASE

class FertilizerInferenceEngine:
    def __init__(self, rules_path='fertilizer_rules.json'):
        self.rules_path = rules_path
        self.kb = self._load_kb()
        self.base_rules = self.kb.get('rules', [])
        self.gejala_mods = self.kb.get('gejala_modifiers', {})
        self.tanah_mods = self.kb.get('tanah_modifiers', {})
        self.meta = self.kb.get('meta', {})

    def _load_kb(self):
        with open(self.rules_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def infer(self, umur_jagung, gejala, jenis_tanah):
        trace = []
        hasil = {
            'umur': umur_jagung,
            'gejala_input': gejala.replace('_', ' ').title(),
            'tanah_input': jenis_tanah.title(),
            'rekomendasi': "Tidak Ada Jadwal Standar",
            'urea': 0, 'sp36': 0, 'kcl': 0, 'cara': '-', 'catatan': '',
            'penjelasan': f"Umur {umur_jagung} HST di luar jadwal.",
            'trace': trace
        }
        base_rule = next((rule for rule in self.base_rules if rule['min_hst'] <= umur_jagung <= rule['max_hst']), None)
        if base_rule:
            hasil.update({k: v for k, v in base_rule.items() if k not in ['min_hst', 'max_hst']})
            trace.append(f"Rule: {base_rule['nama']} ({base_rule['min_hst']}-{base_rule['max_hst']} HST)")
            gejala_mod = self.gejala_mods.get(gejala)
            if gejala_mod:
                hasil['urea'] += gejala_mod.get('urea_tambah', 0)
                hasil['catatan'] += gejala_mod.get('catatan', '') + ' '
                hasil['penjelasan'] += f" Gejala: {gejala_mod.get('catatan', '')}"
                trace.append(f"Modifier Gejala: {gejala_mod.get('catatan', '').strip()}")
            tanah_mod = self.tanah_mods.get(jenis_tanah)
            if tanah_mod:
                hasil['urea'] = round(hasil['urea'] * tanah_mod.get('N_mult', 1.0))
                hasil['sp36'] = round(hasil['sp36'] * tanah_mod.get('P_mult', 1.0))
                hasil['kcl'] = round(hasil['kcl'] * tanah_mod.get('K_mult', 1.0))
                hasil['catatan'] += tanah_mod.get('catatan', '') + ' '
                hasil['penjelasan'] += f" Tanah: {tanah_mod.get('catatan', '')}"
                trace.append(f"Modifier Tanah: {tanah_mod.get('catatan', '').strip()}")
            hasil['rekomendasi'] = base_rule['nama']
            hasil['penjelasan'] = hasil['penjelasan'].strip()
        hasil['urea'] = f"{hasil['urea']} kg/ha" if hasil['urea'] > 0 else "-"
        hasil['sp36'] = f"{hasil['sp36']} kg/ha" if hasil['sp36'] > 0 else "-"
        hasil['kcl'] = f"{hasil['kcl']} kg/ha" if hasil['kcl'] > 0 else "-"
        if hasil['rekomendasi'] == "Tidak Ada Jadwal Standar":
            hasil['urea'] = hasil['sp36'] = hasil['kcl'] = "-"
            hasil['catatan'] += "Konsultasikan dengan ahli."
            trace.append("Tidak ada rule yang cocok untuk umur ini.")
        trace.append(f"Final: Urea {hasil['urea']}, SP36 {hasil['sp36']}, KCl {hasil['kcl']}")
        return hasil

class DiseaseInferenceEngine:
    def __init__(self, rules_path='disease_rules.json', symptoms_path='symptom_list.json'):
        self.rules_path = rules_path
        self.symptoms_path = symptoms_path
        self.kb = self._load_kb()
        self.symptoms = self._load_symptoms()
        self.diseases = self.kb.get('diseases', [])
        self.meta = self.kb.get('meta', {})

    def _load_kb(self):
        with open(self.rules_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _load_symptoms(self):
        with open(self.symptoms_path, 'r', encoding='utf-8') as f:
            return json.load(f).get('symptoms', {})

    def infer(self, selected_gejala_codes):
        trace = []
        if not selected_gejala_codes:
            return {
                "nama": "Tidak Ada Gejala",
                "solusi": "Pilih setidaknya satu gejala.",
                "skor": 0,
                "gejala_dipilih": [],
                "gejala_cocok": [],
                "total_gejala": 0,
                "persentase_cocok": 0,
                "trace": ["Tidak ada gejala yang dipilih."]
            }
        
        hasil_diagnosis = []
        gejala_terpilih = set(selected_gejala_codes)
        
        for penyakit in self.diseases:
            gejala_penyakit = set(penyakit.get('gejala', []))
            cocok = gejala_penyakit.intersection(gejala_terpilih)
            union = gejala_penyakit.union(gejala_terpilih)
            
            if len(union) == 0:
                skor = 0
            else:
                jaccard = len(cocok) / len(union)
                coverage = len(cocok) / len(gejala_penyakit) if len(gejala_penyakit) > 0 else 0
                skor = (jaccard + coverage) / 2
                
            if skor > 0:
                # Get descriptions for symptoms
                gejala_cocok_desc = [self.symptoms.get(kode, f"Gejala {kode}") for kode in cocok]
                gejala_dipilih_desc = [self.symptoms.get(kode, f"Gejala {kode}") for kode in selected_gejala_codes]
                
                hasil_diagnosis.append({
                    "nama": penyakit.get('nama', 'Tanpa Nama'),
                    "kode": penyakit.get('kode', 'Unknown'),
                    "solusi": penyakit.get('solusi', 'Tidak ada solusi.'),
                    "skor": skor,
                    "gejala_cocok": list(cocok),
                    "gejala_cocok_desc": gejala_cocok_desc,
                    "gejala_dipilih": list(selected_gejala_codes),
                    "gejala_dipilih_desc": gejala_dipilih_desc,
                    "total_gejala": len(gejala_penyakit),
                    "persentase_cocok": round(len(cocok) / len(gejala_penyakit) * 100) if len(gejala_penyakit) > 0 else 0,
                    "trace": [
                        f"Rule: {penyakit.get('nama', 'Tanpa Nama')} ({penyakit.get('kode', '-')})",
                        f"Gejala penyakit: {', '.join(gejala_penyakit)}",
                        f"Gejala dipilih: {', '.join(gejala_terpilih)}",
                        f"Cocok: {', '.join(cocok)}",
                        f"Skor: {skor:.2f}"
                    ]
                })
                
        if not hasil_diagnosis:
            return {
                "nama": "Tidak Ditemukan",
                "solusi": "Tidak ada penyakit/hama yang cocok dengan kombinasi gejala ini.",
                "skor": 0,
                "gejala_dipilih": list(selected_gejala_codes),
                "gejala_cocok": [],
                "total_gejala": 0,
                "persentase_cocok": 0,
                "trace": ["Tidak ada penyakit/hama yang cocok dengan kombinasi gejala ini."]
            }
            
        hasil_diagnosis.sort(key=lambda x: (x['skor'], x['persentase_cocok']), reverse=True)
        
        if len(hasil_diagnosis) == 1:
            return hasil_diagnosis[0]
        else:
            return {
                "utama": hasil_diagnosis[0],
                "alternatif": hasil_diagnosis[1:3] if len(hasil_diagnosis) > 1 else [],
                "trace": hasil_diagnosis[0]['trace']
            }

# Inisialisasi engine global
fertilizer_engine = FertilizerInferenceEngine(rules_path='fertilizer_rules.json')
disease_engine = DiseaseInferenceEngine(rules_path='disease_rules.json', symptoms_path='symptom_list.json')

# Fungsi wrapper agar kompatibel dengan route lama

def get_fertilizer_logic(umur_jagung, gejala, jenis_tanah):
    return fertilizer_engine.infer(umur_jagung, gejala, jenis_tanah)

def get_diagnosis_logic(selected_gejala_codes):
    return disease_engine.infer(selected_gejala_codes)

# --- API Routes ---

@app.route('/api/pemupukan', methods=['POST'])
def api_pemupukan():
    """API untuk rekomendasi pemupukan."""
    try:
        data = request.get_json()
        umur = int(data.get('umur_jagung', 0))
        gejala = data.get('gejala', 'normal')
        jenis_tanah = data.get('jenis_tanah', 'sedang')
        
        if umur < 0:
            return jsonify({"error": "Umur tidak boleh negatif."}), 400
            
        hasil = get_fertilizer_logic(umur, gejala, jenis_tanah)
        return jsonify(hasil)
    except Exception as e:
        logger.error(f"API Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/diagnosis', methods=['POST'])
def api_diagnosis():
    """API untuk diagnosis penyakit."""
    try:
        data = request.get_json()
        selected_gejala = data.get('gejala', [])
        
        hasil = get_diagnosis_logic(tuple(selected_gejala))
        return jsonify(hasil)
    except Exception as e:
        logger.error(f"API Error: {e}")
        return jsonify({"error": str(e)}), 500

# --- Web Routes ---

@app.route('/')
def home():
    """Menampilkan halaman menu utama."""
    # Muat knowledge base di awal
    load_knowledge_base()
    current_year = datetime.now().year
    return render_template('index.html', year=current_year)

@app.route('/budidaya')
def budidaya():
    """Menampilkan informasi budidaya jagung."""
    current_year = datetime.now().year
    return render_template('budidaya.html', year=current_year)

@app.route('/kalkulator')
def kalkulator():
    """Menampilkan kalkulator kebutuhan benih dan pupuk."""
    current_year = datetime.now().year
    return render_template('kalkulator.html', year=current_year)

@app.route('/panduan')
def panduan():
    """Menampilkan panduan penggunaan aplikasi."""
    current_year = datetime.now().year
    return render_template('panduan.html', year=current_year)

@app.route('/riwayat')
def riwayat():
    """Menampilkan riwayat konsultasi."""
    current_year = datetime.now().year
    return render_template('riwayat.html', year=current_year)

@app.route('/search')
def search():
    """Pencarian informasi di seluruh aplikasi."""
    query = request.args.get('q', '')
    results = []
    
    if query:
        # Pencarian di informasi budidaya
        if 'lahan' in query.lower() or 'persiapan' in query.lower() or 'tanah' in query.lower():
            results.append({
                'category': 'Budidaya',
                'title': 'Persiapan Lahan',
                'content': 'Informasi tentang pengolahan tanah, kondisi tanah ideal, pH tanah, dan pupuk dasar untuk persiapan lahan jagung.',
                'url': '/budidaya#nav-persiapan'
            })
            
        if 'tanam' in query.lower() or 'benih' in query.lower() or 'biji' in query.lower():
            results.append({
                'category': 'Budidaya',
                'title': 'Penanaman Jagung',
                'content': 'Panduan waktu tanam, jarak tanam, kebutuhan benih, dan teknik penanaman jagung yang benar.',
                'url': '/budidaya#nav-penanaman'
            })
            
        if 'air' in query.lower() or 'irigasi' in query.lower() or 'pengairan' in query.lower():
            results.append({
                'category': 'Budidaya',
                'title': 'Pengairan Jagung',
                'content': 'Informasi kebutuhan air per fase pertumbuhan, teknik irigasi, dan fase kritis kebutuhan air pada jagung.',
                'url': '/budidaya#nav-pengairan'
            })
            
        if 'panen' in query.lower() or 'hasil' in query.lower():
            results.append({
                'category': 'Budidaya',
                'title': 'Panen Jagung',
                'content': 'Panduan waktu panen yang tepat, tanda-tanda jagung siap panen, dan teknik pemanenan yang benar.',
                'url': '/budidaya#nav-panen'
            })
            
        if 'pasca' in query.lower() or 'simpan' in query.lower() or 'kering' in query.lower():
            results.append({
                'category': 'Budidaya',
                'title': 'Pasca Panen',
                'content': 'Informasi penanganan hasil panen, pengeringan, penyimpanan, dan pencegahan kerusakan pada jagung.',
                'url': '/budidaya#nav-pascapanen'
            })
        
        # Pencarian di informasi pemupukan
        if 'pupuk' in query.lower() or 'urea' in query.lower() or 'npk' in query.lower() or 'sp36' in query.lower() or 'kcl' in query.lower():
            results.append({
                'category': 'Pemupukan',
                'title': 'Rekomendasi Pemupukan',
                'content': 'Dapatkan rekomendasi dosis dan jenis pupuk berdasarkan umur tanaman jagung, gejala tanaman, dan jenis tanah.',
                'url': '/pemupukan'
            })
            results.append({
                'category': 'Kalkulator',
                'title': 'Kalkulator Kebutuhan Pupuk',
                'content': 'Hitung jumlah pupuk yang dibutuhkan (Urea, SP-36, KCl, dan pupuk organik) berdasarkan luas lahan dan jenis tanah.',
                'url': '/kalkulator#fertilizer'
            })
        
        # Pencarian di informasi penyakit
        if 'penyakit' in query.lower() or 'hama' in query.lower() or 'bulai' in query.lower() or 'karat' in query.lower() or 'busuk' in query.lower():
            results.append({
                'category': 'Diagnosis',
                'title': 'Diagnosis Penyakit dan Hama',
                'content': 'Identifikasi penyakit dan hama pada tanaman jagung berdasarkan gejala yang terlihat, beserta rekomendasi pengendaliannya.',
                'url': '/diagnosis'
            })
        
        # Pencarian di kalkulator
        if 'kalkulator' in query.lower() or 'hitung' in query.lower():
            results.append({
                'category': 'Kalkulator',
                'title': 'Kalkulator Kebutuhan Benih',
                'content': 'Hitung jumlah benih jagung yang dibutuhkan berdasarkan luas lahan dan jarak tanam yang digunakan.',
                'url': '/kalkulator#seed'
            })
            results.append({
                'category': 'Kalkulator',
                'title': 'Kalkulator Kebutuhan Pupuk',
                'content': 'Hitung jumlah pupuk yang dibutuhkan berdasarkan luas lahan dan jenis tanah Anda.',
                'url': '/kalkulator#fertilizer'
            })
            
        # Pencarian pengingat
        if 'pengingat' in query.lower() or 'notifikasi' in query.lower() or 'agenda' in query.lower() or 'jadwal' in query.lower():
            results.append({
                'category': 'Pengingat',
                'title': 'Pengingat Budidaya',
                'content': 'Atur dan kelola pengingat untuk kegiatan budidaya jagung seperti pemupukan, penyemprotan, dan pengairan.',
                'url': '/kalkulator'
            })
    
    current_year = datetime.now().year
    return render_template('search.html', query=query, results=results, year=current_year)

@app.route('/pemupukan', methods=['GET'])
def form_pemupukan():
    """Menampilkan form pemupukan."""
    current_year = datetime.now().year
    return render_template('pemupukan.html', year=current_year)

@app.route('/rekomendasi', methods=['POST'])
def rekomendasi_pemupukan():
    """Memproses form pemupukan."""
    try:
        umur_str = request.form.get('umur_jagung', '').strip()
        if not umur_str.isdigit():
            flash("Umur harus berupa angka bulat positif", "danger")
            return render_template('pemupukan.html', error="Umur harus berupa angka bulat positif.", year=datetime.now().year)
        umur = int(umur_str)
        if umur < 0:
            flash("Umur tanaman tidak boleh negatif", "danger")
            return render_template('pemupukan.html', error="Umur tidak boleh negatif.", year=datetime.now().year)
        gejala = request.form.get('gejala', 'normal')
        jenis_tanah = request.form.get('jenis_tanah', 'sedang')
        hasil = get_fertilizer_logic(umur, gejala, jenis_tanah)
        logger.info(f"Rekomendasi pemupukan untuk: umur={umur}, gejala={gejala}, tanah={jenis_tanah}")
        # Jika tidak ada rule yang cocok, reasoning trace akan menjelaskan alasannya
        if hasil['rekomendasi'] == "Tidak Ada Jadwal Standar":
            flash("Tidak ada jadwal pemupukan standar untuk umur ini. Lihat penjelasan di bawah.", "warning")
        return render_template('hasil_pemupukan.html', hasil=hasil, year=datetime.now().year)
    except Exception as e:
        logger.error(f"Error pada rekomendasi pemupukan: {e}")
        flash(f"Terjadi kesalahan: {e}", "danger")
        return render_template('pemupukan.html', error=f"Error: {e}", year=datetime.now().year)

@app.route('/diagnosis', methods=['GET'])
def form_diagnosis():
    """Menampilkan form diagnosis."""
    try:
        # Load symptoms directly from symptom_list.json
        with open('symptom_list.json', 'r', encoding='utf-8') as f:
            symptom_data = json.load(f)
            gejala = symptom_data.get('symptoms', {})
        
        current_year = datetime.now().year
        return render_template('diagnosis.html', gejala=gejala, year=current_year)
    except Exception as e:
        logger.error(f"Error loading symptoms: {e}")
        flash(f"Terjadi kesalahan saat memuat daftar gejala: {e}", "danger")
        return redirect('/')

@app.route('/hasil_diagnosis', methods=['POST'])
def hasil_diagnosis():
    """Memproses form diagnosis."""
    try:
        selected_gejala = request.form.getlist('gejala_check')  # Ambil semua checkbox yang dicentang
        
        if not selected_gejala:
            flash("Pilih setidaknya satu gejala untuk melakukan diagnosis", "warning")
            return redirect('/diagnosis')
            
        # Log untuk analisis
        logger.info(f"Diagnosis penyakit untuk gejala: {selected_gejala}")
        
        # Get diagnosis results
        hasil = get_diagnosis_logic(tuple(selected_gejala))
        
        # Pass current year to template for footer
        current_year = datetime.now().year
        
        return render_template('hasil_diagnosis.html', hasil=hasil, year=current_year)
    except Exception as e:
        logger.error(f"Error pada diagnosis: {e}")
        flash(f"Terjadi kesalahan saat melakukan diagnosis: {e}", "danger")
        return redirect('/diagnosis')

@app.route('/refresh_kb', methods=['GET'])
def refresh_knowledge_base():
    """Endpoint untuk memaksa reload knowledge base."""
    try:
        kb = load_knowledge_base(force_reload=True)
        flash("Basis pengetahuan berhasil dimuat ulang", "success")
    except Exception as e:
        flash(f"Gagal memuat ulang basis pengetahuan: {e}", "danger")
    return redirect('/')

# --- Error Handlers ---

@app.errorhandler(404)
def page_not_found(e):
    """Handle 404 errors."""
    current_year = datetime.now().year
    return render_template('error.html', error="Halaman tidak ditemukan", year=current_year), 404

@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors."""
    logger.error(f"Server error: {e}")
    current_year = datetime.now().year
    return render_template('error.html', error="Terjadi kesalahan server", year=current_year), 500

# --- Main ---
if __name__ == '__main__':
    # Muat KB saat aplikasi dimulai
    load_knowledge_base()
    app.run(debug=DEBUG)
