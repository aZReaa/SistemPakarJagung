from flask import Flask, render_template, request, flash, jsonify, redirect, url_for
from functools import lru_cache
from datetime import datetime
import json
import logging
import os

# Import konfigurasi
from config import (
    DEBUG, KNOWLEDGE_BASE_PATH, LOG_FORMAT, LOG_LEVEL,
    LOG_FILE, CACHE_TIMEOUT, APP_ROOT
)

# Konfigurasi logging
logging.basicConfig(
    filename=LOG_FILE,
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='templates', static_folder='static')
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
        self.rules_path = os.path.join(APP_ROOT, rules_path)
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
        self.rules_path = os.path.join(APP_ROOT, rules_path)
        self.symptoms_path = os.path.join(APP_ROOT, symptoms_path)
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
    """Menampilkan halaman kalkulator."""
    current_year = datetime.now().year
    # Logika untuk kalkulator bisa ditambahkan di sini jika ada
    return render_template('kalkulator.html', year=current_year)

@app.route('/panduan')
def panduan():
    """Menampilkan halaman panduan."""
    current_year = datetime.now().year
    return render_template('panduan.html', year=current_year)

@app.route('/riwayat')
def riwayat():
    """Menampilkan halaman riwayat."""
    current_year = datetime.now().year
    return render_template('riwayat.html', year=current_year)


@app.route('/search') # Placeholder, sesuaikan jika ada fungsionalitas search
def search():
    """Menampilkan halaman pencarian (jika ada)."""
    query = request.args.get('q', '')
    # Logika pencarian di sini
    results = [] # Ganti dengan hasil pencarian aktual
    current_year = datetime.now().year
    return render_template('search.html', query=query, results=results, year=current_year)


@app.route('/pemupukan', methods=['GET'])
def form_pemupukan():
    """Menampilkan form untuk rekomendasi pemupukan."""
    # Muat data yang mungkin diperlukan untuk form
    try:
        with open(os.path.join(APP_ROOT,'fertilizer_rules.json'), 'r', encoding='utf-8') as f:
            fertilizer_data = json.load(f)
        
        # Ambil daftar gejala dari gejala_modifiers
        gejala_options = list(fertilizer_data.get('gejala_modifiers', {}).keys())
        # Ambil daftar jenis tanah dari tanah_modifiers
        tanah_options = list(fertilizer_data.get('tanah_modifiers', {}).keys())
        
    except Exception as e:
        logger.error(f"Gagal memuat opsi untuk form pemupukan: {e}")
        gejala_options = ['normal', 'kuning_v', 'ungu', 'pinggir_kuning']
        tanah_options = ['ringan', 'sedang', 'berat']
    
    current_year = datetime.now().year
    return render_template('pemupukan.html', gejala_options=gejala_options, tanah_options=tanah_options, year=current_year)


@app.route('/rekomendasi', methods=['POST'])
def rekomendasi_pemupukan():
    """Memproses form pemupukan dan menampilkan hasil."""
    try:
        umur_jagung = int(request.form.get('umur_jagung', 0))
        gejala = request.form.get('gejala', 'normal')
        jenis_tanah = request.form.get('jenis_tanah', 'sedang')

        if umur_jagung <= 0:
            flash('Umur jagung harus lebih dari 0.', 'error')
            return redirect(request.referrer or url_for('form_pemupukan'))

        hasil = get_fertilizer_logic(umur_jagung, gejala, jenis_tanah)
        current_year = datetime.now().year
        return render_template('hasil_pemupukan.html', hasil=hasil, year=current_year)
    except ValueError:
        flash('Input umur jagung tidak valid.', 'error')
        return redirect(request.referrer or url_for('form_pemupukan'))
    except Exception as e:
        logger.error(f"Error pada rekomendasi_pemupukan: {e}")
        flash('Terjadi kesalahan saat memproses permintaan.', 'error')
        return redirect(request.referrer or url_for('form_pemupukan'))

@app.route('/diagnosis', methods=['GET'])
def form_diagnosis():
    """Menampilkan form untuk diagnosis penyakit."""
    try:
        with open(os.path.join(APP_ROOT, 'symptom_list.json'), 'r', encoding='utf-8') as f:
            symptoms_data = json.load(f)
        gejala = symptoms_data.get('symptoms', {}) # {kode: deskripsi}
    except Exception as e:
        logger.error(f"Gagal memuat daftar gejala: {e}")
        gejala = {}
    current_year = datetime.now().year
    return render_template('diagnosis.html', gejala=gejala, year=current_year)


@app.route('/hasil_diagnosis', methods=['POST'])
def hasil_diagnosis():
    """Memproses form diagnosis dan menampilkan hasil."""
    selected_gejala_codes = request.form.getlist('gejala_check')
    if not selected_gejala_codes:
        flash('Pilih setidaknya satu gejala.', 'warning')
        return redirect(request.referrer or url_for('form_diagnosis'))

    hasil = get_diagnosis_logic(tuple(selected_gejala_codes)) # tuple() untuk memastikan hashable

    # Ambil deskripsi gejala yang dipilih untuk ditampilkan
    try:
        with open(os.path.join(APP_ROOT, 'symptom_list.json'), 'r', encoding='utf-8') as f:
            symptoms_data = json.load(f)
        symptoms_map = symptoms_data.get('symptoms', {})
        selected_symptoms_full = {k: symptoms_map.get(k, k) for k in selected_gejala_codes}
    except Exception as e:
        logger.error(f"Gagal memuat deskripsi gejala: {e}")
        selected_symptoms_full = {k: k for k in selected_gejala_codes}

    current_year = datetime.now().year
    return render_template('hasil_diagnosis.html', hasil=hasil, 
                         gejala_dipilih_map=selected_symptoms_full, year=current_year)


@app.route('/refresh_kb', methods=['GET'])
def refresh_knowledge_base():
    """Memuat ulang knowledge base secara manual."""
    load_knowledge_base(force_reload=True)
    flash('Basis pengetahuan berhasil dimuat ulang.', 'info')
    return redirect(url_for('home'))


# --- Error Handlers ---

@app.errorhandler(404)
def page_not_found(e):
    """Menangani error 404."""
    logger.warning(f"404 Not Found: {request.url} (Error: {e})")
    current_year = datetime.now().year
    return render_template('error.html', error_code=404, error_message="Halaman tidak ditemukan.", year=current_year), 404

@app.errorhandler(500)
def server_error(e):
    """Menangani error 500."""
    logger.error(f"500 Internal Server Error: {request.url} (Error: {e})")
    current_year = datetime.now().year
    return render_template('error.html', error_code=500, error_message="Terjadi kesalahan pada server.", year=current_year), 500

# --- Main ---
if __name__ == '__main__':
    # Muat KB saat aplikasi dimulai
    load_knowledge_base()
    # For Render deployment, use PORT environment variable
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=DEBUG)
