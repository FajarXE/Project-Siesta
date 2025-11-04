import bot.helpers.translations as lang

from bot.settings import bot_set
from bot import BOT_QOBUZ_CLIENTS
# --- MODIFIKASI DIMULAI ---
# Impor manager Beatport untuk memeriksa apakah klien aktif
try:
    from bot.helpers.beatport.manager import beatport_manager
except ImportError:
    # Buat dummy manager jika terjadi error impor agar bot tidak crash
    class DummyManager:
        def __init__(self):
            self.clients = []
    beatport_manager = DummyManager()
# --- MODIFIKASI SELESAI ---

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def fetch_base_buttons():
    main_button = [[InlineKeyboardButton(text=lang.s.MAIN_MENU_BUTTON, callback_data="main_menu")]]
    close_button = [[InlineKeyboardButton(text=lang.s.CLOSE_BUTTON, callback_data="close")]]
    return main_button, close_button

def main_menu():
    inline_keyboard = [
        [
            InlineKeyboardButton(
                text=lang.s.CORE,
                callback_data='corePanel'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.TELEGRAM,
                callback_data='tgPanel'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.PROVIDERS,
                callback_data='providerPanel'
            )
        ]
    ]
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += close_button
    return InlineKeyboardMarkup(inline_keyboard)

def providers_button():
    inline_keyboard = []
    
    # --- MODIFIKASI DIMULAI ---
    # Memeriksa dictionary klien, bukan atribut bot_set
    if BOT_QOBUZ_CLIENTS: 
    # --- MODIFIKASI SELESAI ---
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=lang.s.QOBUZ,
                    callback_data='qbP'
                )
            ]
        )
    if bot_set.deezer:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=lang.s.DEEZER,
                    callback_data='dzP'
                )
            ]
        )
    if bot_set.can_enable_tidal:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=lang.s.TIDAL,
                    callback_data='tdP'
                )
            ]
        )
    
    # --- MODIFIKASI DIMULAI ---
    # Tambahkan tombol Beatport jika kliennya aktif
    if beatport_manager and beatport_manager.clients:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="BEATPORT", # Anda bisa mengganti ini dengan variabel lang.s.BEATPORT jika ada
                    callback_data='bpP'
                )
            ]
        )
    # --- MODIFIKASI SELESAI ---
        
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button + close_button
    return InlineKeyboardMarkup(inline_keyboard)


def tg_button():
    inline_keyboard = [
        [
            InlineKeyboardButton(
                text=lang.s.BOT_PUBLIC.format(bot_set.bot_public),
                callback_data='botPublic'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.ANTI_SPAM.format(bot_set.anti_spam),
                callback_data='antiSpam'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.LANGUAGE,
                callback_data='langPanel'
            )
        ]
    ]
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button + close_button
    return InlineKeyboardMarkup(inline_keyboard)


def core_buttons():
    inline_keyboard = []

    if bot_set.rclone:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"Return Link : {bot_set.link_options}",
                    callback_data='linkOptions'
                )
            ]
        )

    inline_keyboard += [
        [
            InlineKeyboardButton(
                text=f"Upload : {bot_set.upload_mode}",
                callback_data='upload'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.SORT_PLAYLIST.format(bot_set.playlist_sort),
                callback_data='sortPlay'
            ),
            InlineKeyboardButton(
                text=lang.s.DISABLE_SORT_LINK.format(bot_set.disable_sort_link),
                callback_data='sortLinkPlay'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.PLAYLIST_ZIP.format(bot_set.playlist_zip),
                callback_data='playZip'
            ),
            InlineKeyboardButton(
                text=lang.s.PLAYLIST_CONC_BUT.format(bot_set.playlist_conc),
                callback_data='playCONC'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.ARTIST_BATCH_BUT.format(bot_set.artist_batch),
                callback_data='artBATCH'
            ),
            InlineKeyboardButton(
                text=lang.s.ARTIST_ZIP.format(bot_set.artist_zip),
                callback_data='artZip'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.ALBUM_ZIP.format(bot_set.album_zip),
                callback_data='albZip'
            ),
            InlineKeyboardButton(
                text=lang.s.POST_ART_BUT.format(bot_set.art_poster),
                callback_data='albArt'
            )
        ]
    ]
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button + close_button
    return InlineKeyboardMarkup(inline_keyboard)



def language_buttons(languages, selected):
    inline_keyboard = []
    for item in languages:
        text = f"{item.__language__} ✅" if item.__language__ == selected else item.__language__
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=text.upper(),
                    callback_data=f'langSet_{item.__language__}'
                )
            ]
        )
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button+ close_button
    return InlineKeyboardMarkup(inline_keyboard)


# tidal panel
def tidal_buttons():
    inline_keyboard = [
        [
            InlineKeyboardButton(
                text=lang.s.AUTHORIZATION,
                callback_data='tdAuth'
            )
        ]
    ]

    if bot_set.tidal:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=lang.s.QUALITY,
                    callback_data='tdQ'
                )
            ]
        )
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button + close_button
    return InlineKeyboardMarkup(inline_keyboard)

def tidal_auth_buttons():
    inline_keyboard = []
    if bot_set.tidal:
        inline_keyboard += [
            [
                InlineKeyboardButton(
                    text=lang.s.TIDAL_REMOVE_LOGIN,
                    callback_data=f'tdRemove'
                )
            ],
            [
                InlineKeyboardButton(
                    text=lang.s.TIDAL_REFRESH_SESSION,
                    callback_data=f'tdFresh'
                )
            ]
        ]
    elif bot_set.can_enable_tidal:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=lang.s.TIDAL_LOGIN_TV,
                    callback_data=f'tdLogin'
                )
            ]
        )
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button + close_button
    return InlineKeyboardMarkup(inline_keyboard)
    


# qobuz qualities
def qb_button(qualities: dict, user_id: int = 0):
    inline_keyboard = []
    usetting = user_id != 0
    for quality in qualities.values():
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=quality,
                    callback_data=f"qbQ_{quality.replace('✅', '')}" if not usetting else f"uqbs_{quality.replace('✅', '')}"
                )
            ]
        )
    if usetting:
        inline_keyboard.append(
            [
                InlineKeyboardButton(text="Back", callback_data="uset_back")
            ]
        )
    if usetting:
        return InlineKeyboardMarkup(inline_keyboard)
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button + close_button
    return InlineKeyboardMarkup(inline_keyboard)

# tidal qualities
def tidal_quality_button(qualities: dict, user_id: int = 0):
    inline_keyboard = []
    user_dict = bot_set.tidal.user_data.get(user_id, {})
    spatial = user_dict.get("tidal_spatial", bot_set.tidal.spatial)
    usetting = user_id != 0
    for quality in qualities.values():
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=quality,
                    callback_data=f"tdSQ_{quality.replace('✅', '')}" if not user_id else f"utdqs_{quality.replace('✅', '')}" 
                )
            ]
        )

    inline_keyboard.append(
        [
            InlineKeyboardButton(
                    text=F'SPATIAL : {spatial}',
                    callback_data=f"tdSQ_spatial" if not user_id else "utdqs_spatial"
                )
        ]
    )
    if usetting:
        inline_keyboard.append(
            [
                InlineKeyboardButton(text="Back", callback_data="uset_back")
            ]
        )
    if usetting:
        return InlineKeyboardMarkup(inline_keyboard)
    
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button + close_button
    return InlineKeyboardMarkup(inline_keyboard)

# --- MODIFIKASI DIMULAI ---
# Tambahkan fungsi bp_button (Beatport Button)
def bp_button(quality: dict, user_id: int = None):
    """Membuat tombol untuk pengaturan kualitas Beatport."""
    buttons = []
    usetting = user_id is not None
    # Prefix "bpQ" untuk Admin (Provider), "ubps" untuk User (User BeatPort Set)
    prefix = "bpQ" if not usetting else f"ubps"
    
    row = []
    
    # Map ini penting untuk mendapatkan callback_data yang benar
    display_text_map = {
        "lossless": "Lossless (FLAC)",
        "high": "High (AAC 256)",
        "medium": "Medium (AAC 128)"
    }
    
    # quality dict akan terlihat seperti: {"lossless": "Lossless (FLAC)✅", "high": ...}
    for i, (key, value) in enumerate(quality.items()):
        
        # Dapatkan teks display asli (tanpa checkmark) untuk callback
        callback_text = display_text_map.get(key)
        
        if callback_text:
            # Teks tombol adalah 'value' (yang mungkin punya '✅')
            row.append(InlineKeyboardButton(value, callback_data=f"{prefix}_{callback_text}"))
        
        if (i + 1) % 2 == 0 or i == len(quality) - 1:
            buttons.append(row)
            row = []
            
    if usetting:
        # Untuk panel pengguna, hanya tambahkan tombol 'Back'
        buttons.append(
            [
                InlineKeyboardButton(text="Back", callback_data="uset_back")
            ]
        )
        return InlineKeyboardMarkup(buttons)
    
    # Untuk panel admin, tambahkan tombol menu utama & tutup
    main_button, close_button = fetch_base_buttons()
    buttons += main_button + close_button
    return InlineKeyboardMarkup(buttons)
# --- MODIFIKASI SELESAI ---


def usetting_button() -> InlineKeyboardMarkup:
    buttons = []
    
    if bot_set.tidal:
        but = [
            InlineKeyboardButton(
                text=f"Tidal Quality",
                callback_data=f"uset_tidal"
            )
        ]
        buttons.append(but)
        
    # --- MODIFIKASI DIMULAI ---
    # Memeriksa dictionary klien, bukan atribut bot_set
    if BOT_QOBUZ_CLIENTS:
    # --- MODIFIKASI SELESAI ---
        but = [
            InlineKeyboardButton(
                text=f"Qobuz Quality",
                callback_data=f"uset_qobuz"
            )
        ]
        buttons.append(but)
    
    # --- MODIFIKASI DIMULAI ---
    # Tambahkan tombol Beatport jika kliennya aktif
    if beatport_manager and beatport_manager.clients:
        but = [
            InlineKeyboardButton(
                text=f"Beatport Quality",
                callback_data=f"uset_beatport"
            )
        ]
        buttons.append(but)
    # --- MODIFIKASI SELESAI ---
    
    PLAYLIST_ZIP_BUTTON = [InlineKeyboardButton(text="PLAYLIST_ZIP", callback_data="zip_playlist")]
    buttons.append(PLAYLIST_ZIP_BUTTON)
    
    ALBUM_ZIP_BUTTON = [InlineKeyboardButton(text="ALBUM_ZIP", callback_data="zip_album")]
    buttons.append(ALBUM_ZIP_BUTTON)
    
    ART_POSTER_BUTTON = [InlineKeyboardButton(text="ART_POSTER", callback_data="zip_poster")]
    buttons.append(ART_POSTER_BUTTON)
    
    CLOSE_BUTTON = [InlineKeyboardButton(text="Close", callback_data="uset_close")]
    buttons.append(CLOSE_BUTTON)
    
    return InlineKeyboardMarkup(buttons)
