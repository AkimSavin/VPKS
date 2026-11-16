import os
import re
import io
import ssl
import json
import gzip
import zlib
import struct
import uuid
import logging
from html.parser import HTMLParser
import urllib.request
import urllib.parse
import urllib.error
from flask import current_app

from extensions import db
from models.instruction import Instruction, Step, InstructionMaterial
from models.catalogs import Category, Material, Tool, Tag
from models.photo import Photo
from config import ALLOWED_UNITS

# Отключаем строгую проверку локальных SSL-сертификатов для бесперебойного парсинга
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE

BROWSER_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'close',
}

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')
IGNORE_KEYWORDS = (
    'logo', 'icon', 'counter', 'yandex', 'google', 'vk.com', 'mail.ru',
    'facebook', 'telegram', 'viber', 'whatsapp', 'share', 'button',
    'avatar', 'favicon', 'badge', 'rating', 'banner', 'pixel'
)


def safe_fetch_url(url: str, timeout: int = 15) -> bytes:
    """Безопасно загружает содержимое URL с браузерными заголовками и распаковкой сжатия."""
    headers = dict(BROWSER_HEADERS)
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc:
        headers['Referer'] = f"{parsed.scheme}://{parsed.netloc}/"

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as response:
        data = response.read()
        encoding = response.headers.get('Content-Encoding', '').lower()
        if 'gzip' in encoding:
            try:
                data = gzip.decompress(data)
            except Exception:
                pass
        elif 'deflate' in encoding:
            try:
                data = zlib.decompress(data)
            except Exception:
                pass
        return data


def _is_valid_instruction_image(url: str) -> bool:
    """Фильтрует иконки, логотипы, счетчики и социальные кнопки."""
    if not url or url.startswith('data:'):
        return False
    u = url.lower()
    if any(k in u for k in IGNORE_KEYWORDS):
        return False
    return any(ext in u for ext in ('.jpg', '.jpeg', '.png', '.webp', '/upload/', '/iblock/'))


def _deduplicate_and_pick_hd_images(raw_urls: list, base_url: str) -> list:
    """
    Нормализует адреса страниц буклета, отсеивает сжатые миниатюры (resize_cache, thumb, preview)
    при наличии оригинального полноразмерного HD-скана и удаляет дубликаты.
    """
    hd_map = {}
    order_counter = 0

    for raw in raw_urls:
        if not raw:
            continue
        abs_u = urllib.parse.urljoin(base_url, raw.strip())
        clean_path = urllib.parse.urlparse(abs_u).path
        fname = os.path.basename(clean_path).lower()

        if not fname:
            continue

        core_name = re.sub(r'(_thumb|_min|_small|_preview|\.thumb|\.preview)', '', fname)
        is_thumb = any(part in abs_u.lower() for part in ('resize_cache', '/cache/', 'thumb', 'preview', '_small', '_min'))

        if core_name not in hd_map:
            hd_map[core_name] = {'url': abs_u, 'is_thumb': is_thumb, 'order': order_counter}
            order_counter += 1
        else:
            if hd_map[core_name]['is_thumb'] and not is_thumb:
                hd_map[core_name]['url'] = abs_u
                hd_map[core_name]['is_thumb'] = False

    sorted_items = sorted(hd_map.values(), key=lambda x: x['order'])
    return [item['url'] for item in sorted_items]


class RobustHTMLContentExtractor(HTMLParser):
    """HTML-парсер страниц для извлечения метаданных, этапов и страниц буклета."""

    def __init__(self):
        super().__init__()
        self.title = ''
        self.og_title = ''
        self.og_desc = ''
        self.og_image = ''
        self.images = []
        self.list_items = []
        self.paragraphs = []

        self._in_title = False
        self._in_li = False
        self._in_p = False
        self._current_li_text = []
        self._current_p_text = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)

        if tag == 'title':
            self._in_title = True

        elif tag == 'meta':
            prop = attr_dict.get('property', '').lower()
            content = attr_dict.get('content', '').strip()

            if prop in ('og:title', 'twitter:title'):
                self.og_title = content
            elif prop in ('og:description', 'description'):
                self.og_desc = content
            elif prop in ('og:image', 'twitter:image'):
                self.og_image = content

        elif tag == 'img':
            src = attr_dict.get('src') or attr_dict.get('data-src') or attr_dict.get('data-original')
            if src and _is_valid_instruction_image(src):
                self.images.append(src.strip())

        elif tag == 'a':
            href = attr_dict.get('href')
            if href and _is_valid_instruction_image(href):
                self.images.append(href.strip())

        elif tag == 'li':
            self._in_li = True
            self._current_li_text = []

        elif tag == 'p':
            self._in_p = True
            self._current_p_text = []

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False
        elif tag == 'li':
            self._in_li = False
            txt = ' '.join(self._current_li_text).strip()
            if len(txt) > 5:
                self.list_items.append(txt)
        elif tag == 'p':
            self._in_p = False
            txt = ' '.join(self._current_p_text).strip()
            if len(txt) > 20:
                self.paragraphs.append(txt)

    def handle_data(self, data):
        cleaned = data.strip()
        if not cleaned:
            return
        if self._in_title:
            self.title += ' ' + cleaned
        elif self._in_li:
            self._current_li_text.append(cleaned)
        elif self._in_p:
            self._current_p_text.append(cleaned)


def download_and_attach_photo(img_url: str, instruction_id: int, step_id=None, is_cover=False) -> bool:
    """
    Скачивает изображение по ссылке, валидирует размер (до 5 МБ) и формат (JPEG/PNG/WebP),
    сохраняет в папку uploads и создает запись в таблице photos.
    """
    try:
        data = safe_fetch_url(img_url, timeout=12)
        if not data or len(data) > 5 * 1024 * 1024 or len(data) < 32:
            return False

        mime_type = 'image/jpeg'
        ext = '.jpg'

        if data.startswith(b'\xff\xd8\xff'):
            mime_type = 'image/jpeg'
            ext = '.jpg'
        elif data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime_type = 'image/png'
            ext = '.png'
        elif (data.startswith(b'RIFF') and data[8:12] == b'WEBP') or img_url.lower().endswith('.webp'):
            try:
                from PIL import Image
                img_obj = Image.open(io.BytesIO(data))
                if img_obj.mode in ('RGBA', 'LA'):
                    bg = Image.new('RGB', img_obj.size, (255, 255, 255))
                    bg.paste(img_obj, mask=img_obj.split()[-1])
                    img_obj = bg
                else:
                    img_obj = img_obj.convert('RGB')

                out_buf = io.BytesIO()
                img_obj.save(out_buf, format='JPEG', quality=95)
                data = out_buf.getvalue()
                mime_type = 'image/jpeg'
                ext = '.jpg'
            except Exception:
                mime_type = 'image/jpeg'
                ext = '.jpg'
        else:
            mime_type = 'image/jpeg'
            ext = '.jpg'

        fname = f"{uuid.uuid4().hex}{ext}"
        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, fname)

        with open(filepath, 'wb') as f:
            f.write(data)

        if is_cover:
            Photo.query.filter_by(instruction_id=instruction_id, is_cover=True).update({'is_cover': False})

        photo = Photo(
            instruction_id=instruction_id,
            step_id=step_id,
            filename=fname,
            mime_type=mime_type,
            size_bytes=len(data),
            is_cover=is_cover
        )
        db.session.add(photo)
        db.session.flush()
        return True

    except Exception as e:
        logging.warning(f"Не удалось скачать и сохранить изображение {img_url}: {e}")
        return False


def _create_minimal_png_blueprint(width=480, height=280, title="ЧЕРТЕЖ УЗЛА") -> bytes:
    """Генерирует автономный чертеж узла в формате PNG."""
    header = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('!IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr = struct.pack('!I', len(ihdr_data)) + b'IHDR' + ihdr_data + struct.pack('!I', zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff)

    raw_rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            if x < 4 or x >= width - 4 or y < 4 or y >= height - 4:
                row.extend((20, 30, 48))
            elif (x % 24 == 0) or (y % 24 == 0):
                row.extend((32, 60, 95))
            else:
                row.extend((24, 46, 74))
        raw_rows.append(bytes(row))

    compressed = zlib.compress(b''.join(raw_rows))
    idat = struct.pack('!I', len(compressed)) + b'IDAT' + compressed + struct.pack('!I', zlib.crc32(b'IDAT' + compressed) & 0xffffffff)
    iend = struct.pack('!I', 0) + b'IEND' + struct.pack('!I', zlib.crc32(b'IEND') & 0xffffffff)
    return header + ihdr + idat + iend


def attach_step_photo_fallback(instruction_id: int, step_id: int, step_number: int) -> bool:
    """Резервный генератор сборочных схем узла для этапов."""
    try:
        fname = f"{uuid.uuid4().hex}.png"
        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, fname)

        img_bytes = _create_minimal_png_blueprint(480, 280, f"СХЕМА УЗЛА ШАГ {step_number}")
        with open(filepath, 'wb') as f:
            f.write(img_bytes)

        photo = Photo(
            instruction_id=instruction_id,
            step_id=step_id,
            filename=fname,
            mime_type='image/png',
            size_bytes=len(img_bytes),
            is_cover=False
        )
        db.session.add(photo)
        db.session.flush()
        return True
    except Exception as e:
        logging.error(f"Ошибка attach_step_photo_fallback: {e}")
        return False


def parse_and_create_from_url(url: str, owner_id: int) -> Instruction:
    """
    Парсит веб-страницу по ссылке (включая PHP-просмотрщики mir-kubikov.ru/instruction.php,
    cubiform.ru и DIY-порталы), извлекает встроенный PDF или страницы буклета и собирает инструкцию.
    """
    html_content = ""
    raw_response = b""
    try:
        raw_response = safe_fetch_url(url, timeout=15)
        if raw_response.lstrip().startswith(b'%PDF-'):
            return _build_instruction_from_pdf_bytes(
                raw_bytes=raw_response,
                source_filename=os.path.basename(urllib.parse.urlparse(url).path) or "instruction.pdf",
                owner_id=owner_id
            )
        html_content = raw_response.decode('utf-8', errors='ignore')
    except Exception as e:
        logging.warning(f"Ошибка загрузки HTML {url}: {e}")

    articul_match = re.search(r'(?:articul=|/lego/[^/]+/|\b)(\d{4,6})\b', url)
    articul = articul_match.group(1) if articul_match else None

    if html_content:
        pdf_match = re.search(
            r'''(?:src|href|data|file|url)\s*[:=]\s*["']([^"'<>]+\.pdf(?:\?[^"'<>]*)?)["']''',
            html_content,
            re.IGNORECASE
        )
        if pdf_match:
            pdf_url = urllib.parse.urljoin(url, pdf_match.group(1).strip())
            try:
                pdf_bytes = safe_fetch_url(pdf_url, timeout=25)
                if pdf_bytes and pdf_bytes.lstrip().startswith(b'%PDF-'):
                    custom_title = f"Конструктор LEGO {articul}" if articul else None
                    return _build_instruction_from_pdf_bytes(
                        raw_bytes=pdf_bytes,
                        source_filename=os.path.basename(urllib.parse.urlparse(pdf_url).path) or "instruction.pdf",
                        owner_id=owner_id,
                        override_title=custom_title
                    )
            except Exception as e:
                logging.warning(f"Не удалось скачать встроенный PDF по ссылке {pdf_url}: {e}")

    parser = RobustHTMLContentExtractor()
    if html_content:
        try:
            parser.feed(html_content)
        except Exception:
            pass

    raw_found_imgs = list(parser.images)
    regex_imgs = re.findall(
        r'''(?:href|src|data-src|data-original)=["']([^"']+\.(?:jpg|jpeg|png|webp)[^"']*)["']''',
        html_content,
        re.IGNORECASE
    )
    for ri in regex_imgs:
        clean_ri = ri.split('?')[0].strip()
        if _is_valid_instruction_image(clean_ri):
            raw_found_imgs.append(clean_ri)

    all_page_images = _deduplicate_and_pick_hd_images(raw_found_imgs, base_url=url)

    title = parser.og_title or parser.title
    title = re.sub(r'[\r\n\t]+', ' ', title).strip()
    title = re.sub(r'\s{2,}', ' ', title)
    title = re.sub(
        r'(—|-|\|)\s*(Инструкция по сборке|Схемы конструктора|Mir Kubikov|Cubiform|LEGO).*$',
        '',
        title,
        flags=re.IGNORECASE
    ).strip()

    if not title:
        title = f"Конструктор LEGO {articul}" if articul else "Импортированная DIY-инструкция"
    title = title[:120]

    is_lego = bool(articul or 'lego' in url.lower() or 'кубик' in url.lower() or 'cubiform' in url.lower())
    category_name = "Конструкторы и LEGO" if is_lego else "Интернет-крафт"

    cat = Category.query.filter_by(owner_id=owner_id, name=category_name).first()
    if not cat:
        cat = Category(owner_id=owner_id, name=category_name)
        db.session.add(cat)
        db.session.flush()

    description = parser.og_desc or ""
    if not description and parser.paragraphs:
        description = " ".join(parser.paragraphs[:3])
    if not description and articul:
        description = f"Официальная пошаговая инструкция по сборке набора LEGO #{articul}. Импортировано автоматически."
    description = description[:5000]

    cover_image_url = None
    if parser.og_image and _is_valid_instruction_image(parser.og_image):
        cover_image_url = urllib.parse.urljoin(url, parser.og_image)
    else:
        for img_u in all_page_images:
            u_low = img_u.lower()
            if any(k in u_low for k in ('cover', 'box', 'oblojka', 'main', 'preview')):
                cover_image_url = img_u
                break
        if not cover_image_url and all_page_images:
            cover_image_url = all_page_images[0]

    cover_fname = os.path.basename(urllib.parse.urlparse(cover_image_url).path).lower() if cover_image_url else ''
    step_images_pool = []

    for img in all_page_images:
        img_fname = os.path.basename(urllib.parse.urlparse(img).path).lower()
        if cover_image_url and (img == cover_image_url or (cover_fname and img_fname == cover_fname)):
            continue
        step_images_pool.append(img)

    if step_images_pool:
        first_fname = os.path.basename(urllib.parse.urlparse(step_images_pool[0]).path).lower()
        if any(w in first_fname for w in ('cover', 'oblojka', 'box', 'main', 'preview')) or first_fname.endswith(('_0.jpg', '_00.jpg', '_0.png')):
            step_images_pool.pop(0)

    steps_data = []
    if len(step_images_pool) > 0 and (is_lego or len(step_images_pool) >= len(parser.list_items)):
        for idx in range(len(step_images_pool)):
            steps_data.append(f"Лист сборки #{idx + 1}. Соедините детали в точном соответствии со сборочной схемой.")
    elif parser.list_items:
        steps_data = [item[:2000] for item in parser.list_items[:50]]
    else:
        steps_data = [
            "Подготовить рабочее место, распаковать детали и рассортировать их по цветам и типам.",
            "Собрать опорное основание и несущий каркас конструкции.",
            "Смонтировать внешние элементы, детализированные панели и лицевую часть модели.",
            "Выполнить финальную проверку соединений и установить готовую модель на полку."
        ]

    inst = Instruction(
        owner_id=owner_id,
        category_id=cat.id,
        title=title,
        description=description
    )
    db.session.add(inst)
    db.session.flush()

    if cover_image_url:
        download_and_attach_photo(cover_image_url, inst.id, step_id=None, is_cover=True)

    mat_name = f"Набор деталей LEGO #{articul}" if articul else "Комплект материалов проекта"
    mat = Material.query.filter_by(owner_id=owner_id, name=mat_name).first()
    if not mat:
        mat = Material(owner_id=owner_id, name=mat_name)
        db.session.add(mat)
        db.session.flush()
    db.session.add(InstructionMaterial(instruction_id=inst.id, material_id=mat.id, quantity=1.0, unit='шт.'))

    tool_name = "Разделитель элементов (сепаратор)" if is_lego else "Сборочный инструмент"
    tool = Tool.query.filter_by(owner_id=owner_id, name=tool_name).first()
    if not tool:
        tool = Tool(owner_id=owner_id, name=tool_name)
        db.session.add(tool)
        db.session.flush()
    inst.tools.append(tool)

    tag_words = ['импорт']
    if is_lego:
        tag_words.extend(['lego', 'сборка'])
    if articul:
        tag_words.append(str(articul))

    for tw in tag_words:
        tag_clean = tw.lower().strip()
        tg = Tag.query.filter_by(owner_id=owner_id, name=tag_clean).first()
        if not tg:
            tg = Tag(owner_id=owner_id, name=tag_clean)
            db.session.add(tg)
            db.session.flush()
        if tg not in inst.tags:
            inst.tags.append(tg)

    for idx, step_txt in enumerate(steps_data, start=1):
        step = Step(
            instruction_id=inst.id,
            step_number=idx,
            text=step_txt,
            is_completed=False
        )
        db.session.add(step)
        db.session.flush()

        img_attached = False
        if idx - 1 < len(step_images_pool):
            target_img_url = step_images_pool[idx - 1]
            img_attached = download_and_attach_photo(target_img_url, inst.id, step_id=step.id, is_cover=False)

        if not img_attached:
            attach_step_photo_fallback(inst.id, step.id, idx)

    db.session.commit()
    return inst


def _save_pdf_page_image(img_bytes: bytes, upload_folder: str, instruction_id: int, step_id=None, is_cover=False) -> bool:
    """Сохраняет изображение страницы PDF (JPEG/PNG) с контролем лимита 5 МБ на одно фото."""
    if not img_bytes or len(img_bytes) < 32:
        return False

    mime_type = 'image/png' if img_bytes.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg'
    ext = '.png' if mime_type == 'image/png' else '.jpg'

    if len(img_bytes) > 5 * 1024 * 1024:
        try:
            from PIL import Image
            img_obj = Image.open(io.BytesIO(img_bytes)).convert('RGB')
            out_buf = io.BytesIO()
            img_obj.save(out_buf, format='JPEG', quality=75, optimize=True)
            img_bytes = out_buf.getvalue()
            mime_type = 'image/jpeg'
            ext = '.jpg'
        except Exception:
            return False

    if len(img_bytes) > 5 * 1024 * 1024:
        return False

    fname = f"{uuid.uuid4().hex}{ext}"
    fpath = os.path.join(upload_folder, fname)
    with open(fpath, 'wb') as f:
        f.write(img_bytes)

    photo = Photo(
        instruction_id=instruction_id,
        step_id=step_id,
        filename=fname,
        mime_type=mime_type,
        size_bytes=len(img_bytes),
        is_cover=is_cover
    )
    db.session.add(photo)
    return True


def _extract_pdf_pages_multi_engine(raw_bytes: bytes) -> list:
    """
    Извлекает страницы PDF (номер, текст, байты изображения) с помощью доступных библиотек:
    1) PyMuPDF (fitz.open) — полный рендеринг каждой страницы в JPEG;
    2) pypdf / PyPDF2 — извлечение текста и встроенных растровых картинок страниц.
    """
    # Попытка 1: PyMuPDF (проверяем наличие fitz.open, чтобы не попасть на одноименный пустой пакет fitz)
    try:
        import fitz
        if hasattr(fitz, 'open'):
            pages = []
            doc = fitz.open(stream=raw_bytes, filetype="pdf")
            for i, page in enumerate(doc):
                pix = page.get_pixmap(dpi=120)
                img_data = pix.tobytes("jpeg")
                pages.append((i + 1, (page.get_text() or "").strip(), img_data))
            doc.close()
            if pages:
                return pages
    except Exception as e:
        logging.warning(f"PyMuPDF недоступен или вернул ошибку: {e}")

    # Попытка 2: pypdf (извлекает и текст, и встроенные изображения каждого листа PDF)
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        pages = []
        for i, page in enumerate(reader.pages):
            txt = (page.extract_text() or "").strip()
            best_img_bytes = None
            try:
                for img_file in getattr(page, 'images', []):
                    if img_file.data and (best_img_bytes is None or len(img_file.data) > len(best_img_bytes)):
                        best_img_bytes = img_file.data
            except Exception:
                best_img_bytes = None
            pages.append((i + 1, txt, best_img_bytes))
        if pages:
            return pages
    except Exception as e:
        logging.warning(f"pypdf недоступен или вернул ошибку: {e}")

    raise RuntimeError(
        "Для импорта PDF-файлов установите библиотеку в терминале PyCharm: pip install PyMuPDF pypdf"
    )


def _build_instruction_from_pdf_bytes(raw_bytes: bytes, source_filename: str, owner_id: int, override_title: str = None) -> Instruction:
    """
    Конструирует инструкцию из байтов PDF-документа:
    1-я страница становится обложкой, а последующие страницы — пошаговыми этапами с иллюстрациями.
    """
    if not raw_bytes or len(raw_bytes) < 10:
        raise ValueError("Загруженный PDF-файл пуст.")

    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)

    extracted_pages = _extract_pdf_pages_multi_engine(raw_bytes)

    first_page_txt = extracted_pages[0][1] if extracted_pages else ""
    articul_match = re.search(r'\b(\d{4,6})\b', f"{source_filename} {first_page_txt}")
    articul = articul_match.group(1) if articul_match else None
    is_lego = bool(articul and ('lego' in first_page_txt.lower() or 'lego' in source_filename.lower()))

    base_name = os.path.splitext(source_filename or "Инструкция PDF")[0].replace('_', ' ').strip()
    if override_title:
        pdf_title = override_title[:120]
    elif is_lego and articul not in base_name:
        pdf_title = f"{base_name} (LEGO {articul})"[:120]
    else:
        pdf_title = base_name[:120]

    category_name = "Конструкторы и LEGO" if is_lego else "Инструкции PDF"
    cat = Category.query.filter_by(owner_id=owner_id, name=category_name).first()
    if not cat:
        cat = Category(owner_id=owner_id, name=category_name)
        db.session.add(cat)
        db.session.flush()

    inst = Instruction(
        owner_id=owner_id,
        category_id=cat.id,
        title=pdf_title,
        description=f"Импортировано из PDF-буклета «{source_filename}» ({len(extracted_pages)} стр.). Пошаговая сборка по листам."
    )
    db.session.add(inst)
    db.session.flush()

    # 1-я страница -> обложка; страницы 2..N -> этапы 1..(N-1)
    _, _, cover_img_bytes = extracted_pages[0]
    if cover_img_bytes:
        _save_pdf_page_image(cover_img_bytes, upload_folder, inst.id, step_id=None, is_cover=True)

    step_pages = extracted_pages[1:] if len(extracted_pages) > 1 else extracted_pages

    for step_idx, (orig_page_num, page_txt, img_bytes) in enumerate(step_pages, start=1):
        clean_txt = re.sub(r'\s+', ' ', page_txt).strip()
        step_text = (
            f"Страница буклета #{orig_page_num}: {clean_txt}"
            if len(clean_txt) > 8
            else f"Лист буклета #{orig_page_num}. Выполните монтаж узлов по сборочной схеме."
        )[:2000]

        step = Step(
            instruction_id=inst.id,
            step_number=step_idx,
            text=step_text,
            is_completed=False
        )
        db.session.add(step)
        db.session.flush()

        saved = False
        if img_bytes:
            saved = _save_pdf_page_image(img_bytes, upload_folder, inst.id, step_id=step.id, is_cover=False)

        if not saved:
            attach_step_photo_fallback(inst.id, step.id, step_idx)

    tag_list = ['pdf']
    if is_lego:
        tag_list.append('lego')
    if articul:
        tag_list.append(articul)

    for t_name in tag_list:
        tg = Tag.query.filter_by(owner_id=owner_id, name=t_name.lower()).first()
        if not tg:
            tg = Tag(owner_id=owner_id, name=t_name.lower())
            db.session.add(tg)
            db.session.flush()
        if tg not in inst.tags:
            inst.tags.append(tg)

    db.session.commit()
    return inst


def parse_and_create_from_pdf(file_storage, owner_id: int) -> Instruction:
    """Импортирует инструкцию напрямую из загруженного файла PDF."""
    try:
        file_storage.seek(0)
    except Exception:
        pass
    raw_bytes = file_storage.read()
    return _build_instruction_from_pdf_bytes(
        raw_bytes=raw_bytes,
        source_filename=file_storage.filename or "Инструкция PDF",
        owner_id=owner_id
    )


def parse_and_create_from_file(file_storage, owner_id: int) -> Instruction:
    """
    Импортирует полноценную инструкцию из файла формата .PDF, .JSON или .TXT.
    """
    try:
        file_storage.seek(0)
    except Exception:
        pass
    raw_bytes = file_storage.read()
    if not raw_bytes:
        raise ValueError("Загруженный файл пуст.")

    fname = (file_storage.filename or "").lower()
    if fname.endswith('.pdf') or raw_bytes.lstrip().startswith(b'%PDF-'):
        return _build_instruction_from_pdf_bytes(
            raw_bytes=raw_bytes,
            source_filename=file_storage.filename or "Инструкция PDF",
            owner_id=owner_id
        )

    text = raw_bytes.decode('utf-8', errors='ignore').strip()
    data = None

    if text.startswith('{') and text.endswith('}'):
        try:
            data = json.loads(text)
        except Exception:
            data = None

    if data and isinstance(data, dict):
        title = (data.get('title') or 'Инструкция из файла JSON').strip()[:120]
        desc = (data.get('description') or '').strip()[:5000]
        cat_name = (data.get('category') or 'Импортированные').strip()[:60]

        cat = Category.query.filter_by(owner_id=owner_id, name=cat_name).first()
        if not cat:
            cat = Category(owner_id=owner_id, name=cat_name)
            db.session.add(cat)
            db.session.flush()

        inst = Instruction(
            owner_id=owner_id,
            category_id=cat.id,
            title=title,
            description=desc
        )
        db.session.add(inst)
        db.session.flush()

        cover_url = data.get('cover_image')
        if cover_url and isinstance(cover_url, str) and cover_url.startswith(('http://', 'https://')):
            download_and_attach_photo(cover_url, inst.id, is_cover=True)

        for m in data.get('materials', []):
            if isinstance(m, dict):
                m_name = (m.get('name') or '').strip()[:100]
                try:
                    qty = float(m.get('quantity') or 1.0)
                    if qty <= 0:
                        qty = 1.0
                except (ValueError, TypeError):
                    qty = 1.0
                unit = m.get('unit') or 'шт.'
                if unit not in ALLOWED_UNITS:
                    unit = 'шт.'
            else:
                m_name = str(m).strip()[:100]
                qty = 1.0
                unit = 'шт.'

            if m_name:
                mat = Material.query.filter_by(owner_id=owner_id, name=m_name).first()
                if not mat:
                    mat = Material(owner_id=owner_id, name=m_name)
                    db.session.add(mat)
                    db.session.flush()
                db.session.add(InstructionMaterial(instruction_id=inst.id, material_id=mat.id, quantity=qty, unit=unit))

        for t_name in data.get('tools', []):
            clean_t = str(t_name).strip()[:100]
            if clean_t:
                tl = Tool.query.filter_by(owner_id=owner_id, name=clean_t).first()
                if not tl:
                    tl = Tool(owner_id=owner_id, name=clean_t)
                    db.session.add(tl)
                    db.session.flush()
                if tl not in inst.tools:
                    inst.tools.append(tl)

        for tag_name in data.get('tags', []):
            clean_tag = str(tag_name).strip().lstrip('#')[:30]
            if clean_tag:
                tg = Tag.query.filter_by(owner_id=owner_id, name=clean_tag).first()
                if not tg:
                    tg = Tag(owner_id=owner_id, name=clean_tag)
                    db.session.add(tg)
                    db.session.flush()
                if tg not in inst.tags:
                    inst.tags.append(tg)

        steps_list = data.get('steps', [])
        if not steps_list:
            steps_list = ["Выполнить сборку согласно проекту."]

        for idx, st in enumerate(steps_list, start=1):
            if isinstance(st, dict):
                st_text = (st.get('text') or f"Шаг {idx}").strip()[:2000]
                st_img = st.get('image')
            else:
                st_text = str(st).strip()[:2000]
                st_img = None

            step = Step(instruction_id=inst.id, step_number=idx, text=st_text, is_completed=False)
            db.session.add(step)
            db.session.flush()

            if st_img and isinstance(st_img, str) and st_img.startswith(('http://', 'https://')):
                download_and_attach_photo(st_img, inst.id, step_id=step.id, is_cover=False)

        db.session.commit()
        return inst

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("В файле нет читаемого текста.")

    title = lines[0][:120]
    desc = ("\n".join(lines[1:4]))[:5000] if len(lines) > 1 else ""

    cat = Category.query.filter_by(owner_id=owner_id, name='Текстовые заметки').first()
    if not cat:
        cat = Category(owner_id=owner_id, name='Текстовые заметки')
        db.session.add(cat)
        db.session.flush()

    inst = Instruction(owner_id=owner_id, category_id=cat.id, title=title, description=desc)
    db.session.add(inst)
    db.session.flush()

    step_lines = lines[4:] if len(lines) > 4 else lines[1:]
    if not step_lines:
        step_lines = [lines[0]]

    for idx, sl in enumerate(step_lines, start=1):
        step = Step(instruction_id=inst.id, step_number=idx, text=sl[:2000], is_completed=False)
        db.session.add(step)

    db.session.commit()
    return inst