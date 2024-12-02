import logging
from flask import Flask, render_template_string

# Konfigurasi logging
def setup_logging():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler("log.txt"),
                  logging.StreamHandler()],
        level=logging.INFO
    )
    logging.getLogger("flask").setLevel(logging.ERROR)

# Inisialisasi aplikasi Flask
def create_app():
    app = Flask(__name__)
    return app

# Rute utama
@app.route("/")
def homepages():
    homes = "HI COK IDUP NIH"
    return render_template_string(homes)

# Rute tentang
@app.route("/about")
def about():
    about_content = "Tentang Aplikasi Ini"
    return render_template_string(about_content)

# Menangani kesalahan
@app.errorhandler(404)
def page_not_found(e):
    return "404: Halaman Tidak Ditemukan", 404

# Menjalankan aplikasi
if __name__ == "__main__":
    setup_logging()  # Panggil fungsi setup_logging
    app = create_app()  # Panggil fungsi create_app
    app.run(debug=True)  # Aktifkan mode debug untuk pengembangan
