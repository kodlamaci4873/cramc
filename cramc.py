#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ComputerRAMCleaner (CRAMC) v1.1.0 - Masaüstü uygulaması

Linux (Lubuntu/LXQt) : sync + /proc/sys/vm/drop_caches (PageCache, Dentries & Inodes)
                       isteğe bağlı güvenli swap sıfırlama
Windows 10/11        : Working Set + Sistem Önbelleği temizliği (ctypes + psutil)
Depolama             : Kullanıcı geçici klasörlerinde 24 saatten eski normal dosyaların
                       önizlemeli ve onaylı temizliği

Çalıştırma:
    Linux  : sudo python3 cramc.py
    Windows: python cramc.py   (Yönetici olarak çalıştırmak daha etkilidir)
    Test   : python3 cramc.py --selftest     (arayüzsüz motor testi)

Gereksinimler (kaynak koddan çalıştırırken):
    Linux  : python3-tk ve psutil (Windows ölçümü için)
    Windows: psutil

PyInstaller ile üretilen tek dosyalık dağıtımlarda Python/pip kurulumu gerekmez.
"""

import base64
import json
import os
import platform
import queue
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    TK_OK = True
except ImportError:
    tk = None
    ttk = None
    messagebox = None
    TK_OK = False

try:
    import psutil
except ImportError:
    psutil = None

APP_NAME = "ComputerRAMCleaner"
APP_SHORT = "CRAMC"
APP_VERSION = "1.1.0"

MB = 1024 * 1024
GB = 1024 * MB
DROP_CACHES_PATH = "/proc/sys/vm/drop_caches"
OS_NAME = platform.system()
IS_LINUX = OS_NAME == "Linux"
IS_WINDOWS = OS_NAME == "Windows"


# --------------------------------------------------------------------------- #
#  ÇOK DİLLİ ARAYÜZ
# --------------------------------------------------------------------------- #
LANGUAGE_ORDER = ("tr", "en", "es", "fr", "de", "pt", "ru", "ar", "zh", "ja", "hi")
LANGUAGE_NAMES = {
    "tr": "Türkçe", "en": "English", "es": "Español", "fr": "Français",
    "de": "Deutsch", "pt": "Português", "ru": "Русский", "ar": "العربية",
    "zh": "中文", "ja": "日本語", "hi": "हिन्दी",
}
ACTIVE_LANGUAGE = "tr"

# Satır sırası: Türkçe, English, Español, Français, Deutsch, Português,
# Русский, العربية, 中文, 日本語, हिन्दी.
I18N_ROWS = [
    ("✦  Hoş Geldin", ("✦  Hoş Geldin", "✦  Welcome", "✦  Bienvenido", "✦  Bienvenue", "✦  Willkommen", "✦  Boas-vindas", "✦  Добро пожаловать", "✦  أهلاً بك", "✦  欢迎", "✦  ようこそ", "✦  स्वागत है")),
    ("◈  RAM Yönetimi", ("◈  RAM Yönetimi", "◈  RAM Manager", "◈  Gestión de RAM", "◈  Gestion de la RAM", "◈  RAM-Verwaltung", "◈  Gestão de RAM", "◈  Управление RAM", "◈  إدارة الذاكرة", "◈  内存管理", "◈  RAM 管理", "◈  RAM प्रबंधन")),
    ("▣  Depolama", ("▣  Depolama", "▣  Storage", "▣  Almacenamiento", "▣  Stockage", "▣  Speicher", "▣  Armazenamento", "▣  Хранилище", "▣  التخزين", "▣  存储", "▣  ストレージ", "▣  स्टोरेज")),
    ("CRAMC'ye hoş geldin!", ("CRAMC'ye hoş geldin!", "Welcome to CRAMC!", "¡Te damos la bienvenida a CRAMC!", "Bienvenue dans CRAMC !", "Willkommen bei CRAMC!", "Boas-vindas ao CRAMC!", "Добро пожаловать в CRAMC!", "مرحباً بك في CRAMC!", "欢迎使用 CRAMC！", "CRAMC へようこそ！", "CRAMC में आपका स्वागत है!")),
    ("ComputerRAMCleaner; RAM ve sistem önbelleği durumunu izlemenize, işletim sisteminize uygun temizlik işlemlerini seçmenize ve kullanıcı geçici dosyalarını kontrollü biçimde yönetmenize yardımcı olur.", ("ComputerRAMCleaner; RAM ve sistem önbelleği durumunu izlemenize, işletim sisteminize uygun temizlik işlemlerini seçmenize ve kullanıcı geçici dosyalarını kontrollü biçimde yönetmenize yardımcı olur.", "ComputerRAMCleaner helps you monitor RAM and system cache, choose cleanup actions for your operating system, and manage user temporary files safely.", "ComputerRAMCleaner te ayuda a supervisar la RAM y la caché del sistema, elegir acciones de limpieza para tu sistema operativo y administrar de forma segura los archivos temporales del usuario.", "ComputerRAMCleaner vous aide à surveiller la RAM et le cache système, à choisir les opérations adaptées à votre système et à gérer les fichiers temporaires en toute sécurité.", "ComputerRAMCleaner hilft Ihnen, RAM und Systemcache zu überwachen, passende Bereinigungsaktionen auszuwählen und temporäre Benutzerdateien sicher zu verwalten.", "O ComputerRAMCleaner ajuda a monitorar a RAM e o cache do sistema, escolher ações adequadas ao sistema operacional e gerenciar arquivos temporários com segurança.", "ComputerRAMCleaner помогает отслеживать ОЗУ и системный кэш, выбирать подходящую очистку и безопасно управлять временными файлами пользователя.", "يساعدك ComputerRAMCleaner على مراقبة الذاكرة وذاكرة التخزين المؤقت للنظام واختيار عمليات التنظيف المناسبة وإدارة الملفات المؤقتة بأمان.", "ComputerRAMCleaner 可帮助您监控内存和系统缓存，选择适合操作系统的清理操作，并安全管理用户临时文件。", "ComputerRAMCleaner は RAM とシステムキャッシュを監視し、OS に合ったクリーンアップを選択して、一時ファイルを安全に管理できます。", "ComputerRAMCleaner आपको RAM और सिस्टम कैश देखने, OS के अनुसार सफ़ाई चुनने और अस्थायी फ़ाइलों को सुरक्षित रूप से प्रबंधित करने में मदद करता है。")),
    ("RAM Yönetimine Git  →", ("RAM Yönetimine Git  →", "Go to RAM Manager  →", "Ir a Gestión de RAM  →", "Ouvrir la gestion de la RAM  →", "Zur RAM-Verwaltung  →", "Ir para Gestão de RAM  →", "Перейти к управлению RAM  →", "الانتقال إلى إدارة الذاكرة  ←", "前往内存管理  →", "RAM 管理へ  →", "RAM प्रबंधन पर जाएँ  →")),
    ("● Yetkili çalışıyor", ("● Yetkili çalışıyor", "● Running with elevated permissions", "● Ejecutándose con permisos elevados", "● Exécution avec des privilèges élevés", "● Mit erweiterten Rechten gestartet", "● Executando com permissões elevadas", "● Запущено с повышенными правами", "● يعمل بصلاحيات مرتفعة", "● 正在以提升的权限运行", "● 管理者権限で実行中", "● उच्च अनुमति के साथ चल रहा है")),
    ("● Linux: tam temizlik için sudo gerekli", ("● Linux: tam temizlik için sudo gerekli", "● Linux: sudo is required for full cleanup", "● Linux: se necesita sudo para una limpieza completa", "● Linux : sudo est requis pour un nettoyage complet", "● Linux: sudo ist für die vollständige Bereinigung erforderlich", "● Linux: sudo é necessário para a limpeza completa", "● Linux: для полной очистки требуется sudo", "● Linux：完整清理需要 sudo", "● Linux：完全なクリーンアップには sudo が必要", "● Linux: पूरी सफ़ाई के लिए sudo आवश्यक है")),
    ("● Yönetici izni yok; bazı işlemler atlanabilir", ("● Yönetici izni yok; bazı işlemler atlanabilir", "● No administrator rights; some actions may be skipped", "● Sin permisos de administrador; algunas acciones pueden omitirse", "● Sans droits administrateur ; certaines opérations peuvent être ignorées", "● Keine Administratorrechte; einige Aktionen werden möglicherweise übersprungen", "● Sem privilégios de administrador; algumas ações podem ser ignoradas", "● Нет прав администратора; некоторые действия могут быть пропущены", "● 没有管理员权限；部分操作可能会跳过", "● 管理者権限がありません。一部の処理はスキップされます", "● व्यवस्थापक अनुमति नहीं है; कुछ कार्रवाइयाँ छोड़ी जा सकती हैं")),
    ("HIZLI BAŞLANGIÇ REHBERİ", ("HIZLI BAŞLANGIÇ REHBERİ", "QUICK START GUIDE", "GUÍA DE INICIO RÁPIDO", "GUIDE DE DÉMARRAGE RAPIDE", "SCHNELLSTART-ANLEITUNG", "GUIA DE INÍCIO RÁPIDO", "КРАТКОЕ РУКОВОДСТВО", "دليل البدء السريع", "快速入门指南", "クイックスタートガイド", "त्वरित प्रारंभ मार्गदर्शिका")),
    ("Sistemi gözlemle", ("Sistemi gözlemle", "Monitor your system", "Observa tu sistema", "Surveillez votre système", "System überwachen", "Monitore o sistema", "Наблюдайте за системой", "راقب النظام", "监控系统", "システムを確認", "सिस्टम की निगरानी करें")),
    ("RAM, kullanılabilir bellek, önbellek, swap ve işlem sayısını RAM Yönetimi sekmesinde incele.", ("RAM, kullanılabilir bellek, önbellek, swap ve işlem sayısını RAM Yönetimi sekmesinde incele.", "View RAM, available memory, cache, swap, and process count in the RAM Manager tab.", "Consulta la RAM, memoria disponible, caché, swap y número de procesos en la pestaña Gestión de RAM.", "Consultez la RAM, la mémoire disponible, le cache, le swap et le nombre de processus dans l’onglet Gestion de la RAM.", "RAM, verfügbaren Speicher, Cache, Swap und Prozessanzahl im Tab RAM-Verwaltung anzeigen.", "Veja RAM, memória disponível, cache, swap e número de processos na aba Gestão de RAM.", "Просматривайте ОЗУ, свободную память, кэш, swap и число процессов на вкладке управления RAM.", "اعرض الذاكرة المتاحة وذاكرة التخزين المؤقت وSwap وعدد العمليات في علامة تبويب إدارة الذاكرة.", "在“内存管理”选项卡中查看内存、可用内存、缓存、交换空间和进程数量。", "RAM प्रबंधन टैब में RAM, उपलब्ध मेमोरी, कैश, स्वैप और प्रक्रियाओं की संख्या देखें।")),
    ("İşlemleri seç", ("İşlemleri seç", "Choose actions", "Elige las acciones", "Choisissez les actions", "Aktionen auswählen", "Escolha as ações", "Выберите действия", "اختر الإجراءات", "选择操作", "処理を選択", "कार्रवाइयाँ चुनें")),
    ("Linux veya Windows için gösterilen seçenekleri ihtiyacına göre işaretle. Swap sıfırlama isteğe bağlıdır.", ("Linux veya Windows için gösterilen seçenekleri ihtiyacına göre işaretle. Swap sıfırlama isteğe bağlıdır.", "Select the options shown for Linux or Windows as needed. Swap reset is optional.", "Marca las opciones disponibles para Linux o Windows según lo necesites. Restablecer swap es opcional.", "Cochez les options proposées pour Linux ou Windows selon vos besoins. La réinitialisation du swap est facultative.", "Wählen Sie die angezeigten Optionen für Linux oder Windows nach Bedarf aus. Das Zurücksetzen des Swap ist optional.", "Marque as opções exibidas para Linux ou Windows conforme necessário. A redefinição do swap é opcional.", "Выберите нужные параметры для Linux или Windows. Сброс swap необязателен.", "根据需要选择为 Linux 或 Windows 显示的选项。重置 Swap 是可选的。", "必要に応じて Linux または Windows の項目を選択します。Swap のリセットは任意です。", "ज़रूरत के अनुसार Linux या Windows के विकल्प चुनें। Swap रीसेट करना वैकल्पिक है।")),
    ("Önizle ve uygula", ("Önizle ve uygula", "Preview and apply", "Previsualiza y aplica", "Prévisualisez et appliquez", "Vorschau und anwenden", "Pré-visualize e aplique", "Просмотрите и примените", "عاين ثم نفّذ", "预览并应用", "プレビューして実行", "पूर्वावलोकन करें और लागू करें")),
    ("Tahmini kazanımı üst sınır olarak değerlendir; ardından RAM TEMİZLE düğmesiyle işlemi başlat.", ("Tahmini kazanımı üst sınır olarak değerlendir; ardından RAM TEMİZLE düğmesiyle işlemi başlat.", "Treat the estimated gain as an upper bound, then start the operation with CLEAN RAM.", "Considera la ganancia estimada como un límite superior y luego inicia la operación con LIMPIAR RAM.", "Considérez le gain estimé comme une limite supérieure, puis lancez l’opération avec NETTOYER LA RAM.", "Betrachten Sie den geschätzten Gewinn als Obergrenze und starten Sie den Vorgang mit RAM BEREINIGEN.", "Considere o ganho estimado como um limite máximo e inicie a operação em LIMPAR RAM.", "اعتبر التحسن المقدّر حداً أقصى، ثم ابدأ العملية باستخدام تنظيف الذاكرة.", "估算的释放量仅为上限，然后点击“清理内存”开始操作。", "推定値は上限として扱い、「RAM をクリーンアップ」を押して実行します。", "अनुमानित लाभ को अधिकतम सीमा मानें, फिर RAM साफ़ करें बटन से प्रक्रिया शुरू करें।")),
    ("GÜVENLİK NOTU  •  Bellek önbelleklerini temizlemek her zaman performans artışı sağlamaz. Sistemler bu belleği ihtiyaç olduğunda otomatik geri kazanabilir. Depolama sekmesi yalnızca kullanıcının geçici klasörlerinde 24 saatten eski dosyaları listeler; silmeden önce önizleme ve onay ister.", ("GÜVENLİK NOTU  •  Bellek önbelleklerini temizlemek her zaman performans artışı sağlamaz. Sistemler bu belleği ihtiyaç olduğunda otomatik geri kazanabilir. Depolama sekmesi yalnızca kullanıcının geçici klasörlerinde 24 saatten eski dosyaları listeler; silmeden önce önizleme ve onay ister.", "SAFETY NOTE  •  Clearing memory caches does not always improve performance. Systems can reclaim this memory automatically when needed. The Storage tab lists only files older than 24 hours in user temporary folders and asks for preview and confirmation before deletion.", "NOTA DE SEGURIDAD  •  Limpiar las cachés de memoria no siempre mejora el rendimiento. El sistema puede recuperar esta memoria automáticamente cuando la necesite. La pestaña Almacenamiento solo muestra archivos de más de 24 horas en carpetas temporales del usuario y pide una vista previa y confirmación antes de borrarlos.", "SÉCURITÉ  •  Vider les caches mémoire n’améliore pas toujours les performances. Le système peut récupérer cette mémoire automatiquement si nécessaire. L’onglet Stockage liste uniquement les fichiers de plus de 24 heures dans les dossiers temporaires de l’utilisateur et demande un aperçu et une confirmation avant suppression.", "SICHERHEITSHINWEIS  •  Das Leeren von Speichercaches verbessert nicht immer die Leistung. Das System kann diesen Speicher bei Bedarf automatisch zurückgewinnen. Der Speicher-Tab listet nur Dateien in Benutzer-Temp-Ordnern auf, die älter als 24 Stunden sind, und verlangt vor dem Löschen eine Vorschau und Bestätigung.", "NOTA DE SEGURANÇA  •  Limpar caches de memória nem sempre melhora o desempenho. O sistema pode recuperar essa memória automaticamente quando necessário. A aba Armazenamento lista apenas arquivos com mais de 24 horas nas pastas temporárias do usuário e exige pré-visualização e confirmação antes de excluir.", "ПРИМЕЧАНИЕ ПО БЕЗОПАСНОСТИ  •  Очистка кэша памяти не всегда повышает производительность. Система может автоматически освободить эту память при необходимости. Вкладка хранилища показывает только файлы старше 24 часов во временных папках пользователя и требует предварительного просмотра и подтверждения перед удалением.", "ملاحظة أمان  •  لا يؤدي مسح ذاكرة التخزين المؤقت دائماً إلى تحسين الأداء. يمكن للنظام استعادة هذه الذاكرة تلقائياً عند الحاجة. تعرض علامة تبويب التخزين الملفات الأقدم من 24 ساعة في المجلدات المؤقتة للمستخدم فقط، وتطلب المعاينة والتأكيد قبل الحذف.", "安全提示  •  清理内存缓存并不总能提升性能。系统可在需要时自动回收这些内存。“存储”选项卡仅列出用户临时文件夹中超过 24 小时的文件，并在删除前要求预览和确认。", "安全上の注意  •  メモリキャッシュを消去しても、常に性能が向上するわけではありません。必要に応じてシステムが自動的に回収できます。ストレージタブはユーザーの一時フォルダー内にある24時間以上前のファイルのみを表示し、削除前にプレビューと確認を求めます。", "सुरक्षा सूचना  •  मेमोरी कैश साफ़ करने से हमेशा प्रदर्शन बेहतर नहीं होता। सिस्टम ज़रूरत पड़ने पर इस मेमोरी को अपने आप वापस प्राप्त कर सकता है। स्टोरेज टैब केवल उपयोगकर्ता के अस्थायी फ़ोल्डरों में 24 घंटे से पुरानी फ़ाइलें दिखाता है और हटाने से पहले पूर्वावलोकन व पुष्टि माँगता है।")),
    ("DEPOLAMA YÖNETİMİ", ("DEPOLAMA YÖNETİMİ", "STORAGE MANAGEMENT", "GESTIÓN DE ALMACENAMIENTO", "GESTION DU STOCKAGE", "SPEICHERVERWALTUNG", "GESTÃO DE ARMAZENAMENTO", "УПРАВЛЕНИЕ ХРАНИЛИЩЕМ", "إدارة التخزين", "存储管理", "ストレージ管理", "स्टोरेज प्रबंधन")),
    ("Geçici dosyaları güvenle gözden geçir", ("Geçici dosyaları güvenle gözden geçir", "Review temporary files safely", "Revisa los archivos temporales de forma segura", "Examinez les fichiers temporaires en toute sécurité", "Temporäre Dateien sicher überprüfen", "Revise arquivos temporários com segurança", "Безопасный просмотр временных файлов", "راجع الملفات المؤقتة بأمان", "安全检查临时文件", "一時ファイルを安全に確認", "अस्थायी फ़ाइलों की सुरक्षित समीक्षा करें")),
    ("CRAMC yalnızca kullanıcı geçici klasörlerini tarar. Varsayılan olarak 24 saatten eski normal dosyalar listelenir; sistem klasörleri, tarayıcı önbellekleri, İndirilenler klasörü ve sembolik bağlantı hedefleri taranmaz.", ("CRAMC yalnızca kullanıcı geçici klasörlerini tarar. Varsayılan olarak 24 saatten eski normal dosyalar listelenir; sistem klasörleri, tarayıcı önbellekleri, İndirilenler klasörü ve sembolik bağlantı hedefleri taranmaz.", "CRAMC scans only user temporary folders. By default, normal files older than 24 hours are listed; system folders, browser caches, Downloads, and symbolic-link targets are not scanned.", "CRAMC solo analiza las carpetas temporales del usuario. De forma predeterminada, se muestran archivos normales de más de 24 horas; no se analizan carpetas del sistema, cachés del navegador, Descargas ni destinos de enlaces simbólicos.", "CRAMC analyse uniquement les dossiers temporaires de l’utilisateur. Par défaut, les fichiers ordinaires de plus de 24 heures sont listés ; les dossiers système, caches du navigateur, téléchargements et cibles de liens symboliques ne sont pas analysés.", "CRAMC durchsucht nur temporäre Benutzerordner. Standardmäßig werden normale Dateien angezeigt, die älter als 24 Stunden sind; Systemordner, Browser-Caches, Downloads und Ziele symbolischer Links werden nicht durchsucht.", "O CRAMC verifica apenas pastas temporárias do usuário. Por padrão, arquivos comuns com mais de 24 horas são listados; pastas do sistema, caches do navegador, Downloads e destinos de links simbólicos não são verificados.", "CRAMC сканирует только временные папки пользователя. По умолчанию показываются обычные файлы старше 24 часов; системные папки, кэш браузера, загрузки и цели символических ссылок не сканируются.", "يفحص CRAMC المجلدات المؤقتة للمستخدم فقط. تُعرض افتراضياً الملفات العادية الأقدم من 24 ساعة؛ ولا يتم فحص مجلدات النظام أو ذاكرة المتصفح أو التنزيلات أو أهداف الروابط الرمزية.", "CRAMC 仅扫描用户临时文件夹。默认列出超过 24 小时的普通文件；不会扫描系统文件夹、浏览器缓存、下载目录或符号链接目标。", "CRAMC はユーザーの一時フォルダーのみをスキャンします。既定では24時間以上前の通常ファイルを一覧表示し、システムフォルダー、ブラウザーキャッシュ、ダウンロード、シンボリックリンク先は対象外です。", "CRAMC केवल उपयोगकर्ता के अस्थायी फ़ोल्डरों को स्कैन करता है। डिफ़ॉल्ट रूप से 24 घंटे से पुरानी सामान्य फ़ाइलें दिखाई जाती हैं; सिस्टम फ़ोल्डर, ब्राउज़र कैश, डाउनलोड और प्रतीकात्मक लिंक लक्ष्य स्कैन नहीं होते।")),
    ("Tarama yapılmadı. Önce geçici dosyaları tara.", ("Tarama yapılmadı. Önce geçici dosyaları tara.", "No scan has been run. Scan temporary files first.", "Aún no se ha realizado un análisis. Analiza primero los archivos temporales.", "Aucune analyse effectuée. Analysez d’abord les fichiers temporaires.", "Noch kein Scan durchgeführt. Scannen Sie zuerst temporäre Dateien.", "Nenhuma verificação foi executada. Verifique primeiro os arquivos temporários.", "Сканирование не выполнялось. Сначала просканируйте временные файлы.", "لم يتم الفحص. افحص الملفات المؤقتة أولاً.", "尚未扫描。请先扫描临时文件。", "まだスキャンされていません。先に一時ファイルをスキャンしてください。", "अभी स्कैन नहीं हुआ। पहले अस्थायी फ़ाइलें स्कैन करें।")),
    ("GEÇİCİ DOSYA", ("GEÇİCİ DOSYA", "TEMPORARY FILE", "ARCHIVO TEMPORAL", "FICHIER TEMPORAIRE", "TEMPORÄRE DATEI", "ARQUIVO TEMPORÁRIO", "ВРЕМЕННЫЙ ФАЙЛ", "ملف مؤقت", "临时文件", "一時ファイル", "अस्थायी फ़ाइल")),
    ("BOYUT", ("BOYUT", "SIZE", "TAMAÑO", "TAILLE", "GRÖSSE", "TAMANHO", "РАЗМЕР", "الحجم", "大小", "サイズ", "आकार")),
    ("SON DEĞİŞİKLİK", ("SON DEĞİŞİKLİK", "LAST MODIFIED", "ÚLTIMA MODIFICACIÓN", "DERNIÈRE MODIFICATION", "ZULETZT GEÄNDERT", "ÚLTIMA ALTERAÇÃO", "ПОСЛЕДНЕЕ ИЗМЕНЕНИЕ", "آخر تعديل", "最后修改", "最終更新", "अंतिम संशोधन")),
    ("GEÇİCİ DOSYALARI TARA", ("GEÇİCİ DOSYALARI TARA", "SCAN TEMPORARY FILES", "ANALIZAR ARCHIVOS TEMPORALES", "ANALYSER LES FICHIERS TEMPORAIRES", "TEMPORÄRE DATEIEN SCANNEN", "VERIFICAR ARQUIVOS TEMPORÁRIOS", "СКАНИРОВАТЬ ВРЕМЕННЫЕ ФАЙЛЫ", "افحص الملفات المؤقتة", "扫描临时文件", "一時ファイルをスキャン", "अस्थायी फ़ाइलें स्कैन करें")),
    ("ÖNİZLEMEDEKİ DOSYALARI SİL", ("ÖNİZLEMEDEKİ DOSYALARI SİL", "DELETE PREVIEWED FILES", "ELIMINAR ARCHIVOS PREVISUALIZADOS", "SUPPRIMER LES FICHIERS PRÉVISUALISÉS", "ANGEZEIGTE DATEIEN LÖSCHEN", "EXCLUIR ARQUIVOS VISUALIZADOS", "УДАЛИТЬ ФАЙЛЫ ИЗ ПРЕДПРОСМОТРА", "احذف الملفات المعاينة", "删除预览中的文件", "プレビューしたファイルを削除", "पूर्वावलोकित फ़ाइलें हटाएँ")),
    ("Yalnızca listelenen dosyalar silinir; onay gerekir.", ("Yalnızca listelenen dosyalar silinir; onay gerekir.", "Only listed files are deleted; confirmation is required.", "Solo se eliminan los archivos listados; se requiere confirmación.", "Seuls les fichiers listés sont supprimés ; une confirmation est requise.", "Nur aufgelistete Dateien werden gelöscht; eine Bestätigung ist erforderlich.", "Somente os arquivos listados serão excluídos; é necessária confirmação.", "تُحذف الملفات المدرجة فقط؛ يلزم التأكيد.", "仅删除列表中的文件；需要确认。", "一覧に表示されたファイルのみ削除され、確認が必要です。", "केवल सूचीबद्ध फ़ाइलें हटाई जाएँगी; पुष्टि आवश्यक है।")),
    ("Geçici klasörler taranıyor…", ("Geçici klasörler taranıyor…", "Scanning temporary folders…", "Analizando carpetas temporales…", "Analyse des dossiers temporaires…", "Temporäre Ordner werden durchsucht…", "Verificando pastas temporárias…", "Сканирование временных папок…", "جارٍ فحص المجلدات المؤقتة…", "正在扫描临时文件夹…", "一時フォルダーをスキャン中…", "अस्थायी फ़ोल्डर स्कैन हो रहे हैं…")),
    ("Geçici dosyaları sil", ("Geçici dosyaları sil", "Delete temporary files", "Eliminar archivos temporales", "Supprimer les fichiers temporaires", "Temporäre Dateien löschen", "Excluir arquivos temporários", "Удалить временные файлы", "حذف الملفات المؤقتة", "删除临时文件", "一時ファイルを削除", "अस्थायी फ़ाइलें हटाएँ")),
    ("Devam etmek istiyor musunuz?", ("Devam etmek istiyor musunuz?", "Do you want to continue?", "¿Quieres continuar?", "Voulez-vous continuer ?", "Möchten Sie fortfahren?", "Deseja continuar?", "Продолжить?", "هل تريد المتابعة؟", "是否继续？", "続行しますか？", "क्या आप जारी रखना चाहते हैं?")),
    ("Önizlemede listelenen dosyalar tekrar doğrulanıyor ve temizleniyor…", ("Önizlemede listelenen dosyalar tekrar doğrulanıyor ve temizleniyor…", "Revalidating and cleaning the files shown in the preview…", "Volviendo a validar y limpiando los archivos de la vista previa…", "Nouvelle vérification et nettoyage des fichiers prévisualisés…", "Die in der Vorschau aufgeführten Dateien werden erneut geprüft und bereinigt…", "Validando novamente e limpando os arquivos da pré-visualização…", "Повторная проверка и очистка файлов из предварительного просмотра…", "جارٍ إعادة التحقق من الملفات المعروضة وتنظيفها…", "正在重新验证并清理预览中的文件…", "プレビューされたファイルを再確認して削除中…", "पूर्वावलोकन में दिखाई गई फ़ाइलों की दोबारा जाँच और सफ़ाई हो रही है…")),
    ("Bulunan dosya: ", ("Bulunan dosya: ", "Files found: ", "Archivos encontrados: ", "Fichiers trouvés : ", "Gefundene Dateien: ", "Arquivos encontrados: ", "Найдено файлов: ", "الملفات الموجودة: ", "找到的文件：", "見つかったファイル: ", "मिली फ़ाइलें: ")),
    ("Toplam boyut: ", ("Toplam boyut: ", "Total size: ", "Tamaño total: ", "Taille totale : ", "Gesamtgröße: ", "Tamanho total: ", "Общий размер: ", "الحجم الإجمالي: ", "总大小：", "合計サイズ: ", "कुल आकार: ")),
    ("Yaş eşiği: 24 saat", ("Yaş eşiği: 24 saat", "Age threshold: 24 hours", "Antigüedad mínima: 24 horas", "Âge minimal : 24 heures", "Altersgrenze: 24 Stunden", "Limite de idade: 24 horas", "Возрастной порог: 24 часа", "حد العمر: 24 ساعة", "时间阈值：24 小时", "経過時間の基準: 24時間", "आयु सीमा: 24 घंटे")),
    (" dosya gösteriliyor ve yalnızca bunlar silme önizlemesine dahil", (" dosya gösteriliyor ve yalnızca bunlar silme önizlemesine dahil", " files shown; only these are included in the deletion preview", " archivos mostrados; solo estos se incluyen en la vista previa de eliminación", " fichiers affichés ; seuls ceux-ci sont inclus dans l’aperçu de suppression", " Dateien werden angezeigt; nur diese sind in der Löschvorschau enthalten", " arquivos exibidos; somente estes entram na pré-visualização da exclusão", " файлов показано; только они включены в предпросмотр удаления", " ملف معروض؛ وهي فقط ضمن معاينة الحذف", " 个文件已显示；仅这些文件会包含在删除预览中", " 件を表示。削除プレビューに含まれるのはこれらのみ", " फ़ाइलें दिखाई गईं; केवल इन्हें हटाने के पूर्वावलोकन में शामिल किया गया है")),
    ("Güvenlik sınırı nedeniyle tarama 20.000 dosyada durdu", ("Güvenlik sınırı nedeniyle tarama 20.000 dosyada durdu", "Scan stopped at 20,000 files due to a safety limit", "El análisis se detuvo en 20.000 archivos por seguridad", "L’analyse s’est arrêtée à 20 000 fichiers par sécurité", "Der Scan wurde aus Sicherheitsgründen bei 20.000 Dateien gestoppt", "A verificação parou em 20.000 arquivos por segurança", "Сканирование остановлено на 20 000 файлах из-за ограничения безопасности", "توقف الفحص عند 20,000 ملف بسبب حد الأمان", "安全限制：扫描在 20,000 个文件处停止", "安全制限により20,000ファイルでスキャンを停止しました", "सुरक्षा सीमा के कारण स्कैन 20,000 फ़ाइलों पर रुक गया")),
    ("Erişim/okuma hatası: ", ("Erişim/okuma hatası: ", "Access/read errors: ", "Errores de acceso/lectura: ", "Erreurs d’accès/lecture : ", "Zugriffs-/Lesefehler: ", "Erros de acesso/leitura: ", "Ошибки доступа/чтения: ", "أخطاء الوصول/القراءة: ", "访问/读取错误：", "アクセス/読み取りエラー: ", "पहुँच/पठन त्रुटियाँ: ")),
    ("Uygun geçici dosya bulunamadı. Sistem ve kullanıcı klasörleri korunmuştur.", ("Uygun geçici dosya bulunamadı. Sistem ve kullanıcı klasörleri korunmuştur.", "No eligible temporary files found. System and user folders were preserved.", "No se encontraron archivos temporales aptos. Se conservaron las carpetas del sistema y del usuario.", "Aucun fichier temporaire admissible trouvé. Les dossiers système et utilisateur ont été préservés.", "Keine geeigneten temporären Dateien gefunden. System- und Benutzerordner wurden geschützt.", "Nenhum arquivo temporário elegível encontrado. As pastas do sistema e do usuário foram preservadas.", "Подходящие временные файлы не найдены. Системные и пользовательские папки сохранены.", "لم يتم العثور على ملفات مؤقتة مناسبة. تم الحفاظ على مجلدات النظام والمستخدم.", "未找到符合条件的临时文件。系统和用户文件夹已保留。", "対象となる一時ファイルはありません。システムとユーザーフォルダーは保護されています。", "कोई उपयुक्त अस्थायी फ़ाइल नहीं मिली। सिस्टम और उपयोगकर्ता फ़ोल्डर सुरक्षित रखे गए हैं।")),
    ("Temizlik tamamlandı: ", ("Temizlik tamamlandı: ", "Cleanup complete: ", "Limpieza completada: ", "Nettoyage terminé : ", "Bereinigung abgeschlossen: ", "Limpeza concluída: ", "Очистка завершена: ", "اكتمل التنظيف: ", "清理完成：", "クリーンアップ完了: ", "सफ़ाई पूरी हुई: ")),
    (" dosya silindi (", (" dosya silindi (", " files deleted (", " archivos eliminados (", " fichiers supprimés (", " Dateien gelöscht (", " arquivos excluídos (", " файлов удалено (", " ملفاً تم حذفه (", " 个文件已删除（", " 件のファイルを削除 (", " फ़ाइलें हटाई गईं (")),
    ("). Atlanan dosya: ", ("). Atlanan dosya: ", "). Skipped files: ", "). Archivos omitidos: ", "). Fichiers ignorés : ", "). Übersprungene Dateien: ", "). Arquivos ignorados: ", "). Пропущено файлов: ", "). الملفات المتخطاة: ", "）。跳过的文件：", "）。スキップしたファイル: ", ")। छोड़ी गई फ़ाइलें: ")),
    (". Son durumu görmek için yeniden tarayın.", (". Son durumu görmek için yeniden tarayın.", ". Scan again to see the latest status.", ". Vuelve a analizar para ver el estado más reciente.", ". Relancez l’analyse pour voir le dernier état.", ". Scannen Sie erneut, um den aktuellen Status zu sehen.", ". Verifique novamente para ver o estado atualizado.", ". Просканируйте снова, чтобы увидеть актуальное состояние.", ". أعد الفحص لرؤية الحالة الأخيرة.", "。重新扫描以查看最新状态。", "。最新の状態を確認するには再スキャンしてください。", "। नवीनतम स्थिति देखने के लिए फिर से स्कैन करें।")),
    ("Depolama işlemi başarısız: ", ("Depolama işlemi başarısız: ", "Storage operation failed: ", "Falló la operación de almacenamiento: ", "Échec de l’opération de stockage : ", "Speichervorgang fehlgeschlagen: ", "Falha na operação de armazenamento: ", "Ошибка операции с хранилищем: ", "فشلت عملية التخزين: ", "存储操作失败：", "ストレージ操作に失敗しました: ", "स्टोरेज प्रक्रिया विफल हुई: ")),
    ("RAM Temizleme ve Optimizasyon Aracı", ("RAM Temizleme ve Optimizasyon Aracı", "RAM Cleaning and Optimization Tool", "Herramienta de limpieza y optimización de RAM", "Outil de nettoyage et d’optimisation de la RAM", "RAM-Bereinigungs- und Optimierungstool", "Ferramenta de limpeza e otimização de RAM", "Инструмент очистки и оптимизации RAM", "أداة تنظيف وتحسين الذاكرة", "内存清理与优化工具", "RAM クリーニング・最適化ツール", "RAM सफ़ाई और अनुकूलन टूल")),
    ("●  ROOT YETKİSİ", ("●  ROOT YETKİSİ", "●  ROOT ACCESS", "●  ACCESO ROOT", "●  ACCÈS ROOT", "●  ROOT-ZUGRIFF", "●  ACESSO ROOT", "●  ROOT-ДОСТУП", "●  صلاحيات ROOT", "●  ROOT 权限", "●  ROOT 権限", "●  ROOT एक्सेस")),
    ("●  YÖNETİCİ", ("●  YÖNETİCİ", "●  ADMINISTRATOR", "●  ADMINISTRADOR", "●  ADMINISTRATEUR", "●  ADMINISTRATOR", "●  ADMINISTRADOR", "●  АДМИНИСТРАТОР", "●  مسؤول النظام", "●  管理员", "●  管理者", "●  व्यवस्थापक")),
    ("●  SUDO YOK", ("●  SUDO YOK", "●  NO SUDO", "●  SIN SUDO", "●  SANS SUDO", "●  KEIN SUDO", "●  SEM SUDO", "●  НЕТ SUDO", "●  لا يوجد SUDO", "●  无 SUDO", "●  SUDO なし", "●  SUDO नहीं")),
    ("●  STANDART KULLANICI", ("●  STANDART KULLANICI", "●  STANDARD USER", "●  USUARIO ESTÁNDAR", "●  UTILISATEUR STANDARD", "●  STANDARD-BENUTZER", "●  USUÁRIO PADRÃO", "●  ОБЫЧНЫЙ ПОЛЬЗОВАТЕЛЬ", "●  مستخدم عادي", "●  标准用户", "●  標準ユーザー", "●  सामान्य उपयोगकर्ता")),
    ("Tam temizlik için sudo ile çalıştırın:  sudo python3 cramc.py", ("Tam temizlik için sudo ile çalıştırın:  sudo python3 cramc.py", "Run with sudo for full cleanup:  sudo python3 cramc.py", "Ejecuta con sudo para una limpieza completa:  sudo python3 cramc.py", "Exécutez avec sudo pour un nettoyage complet :  sudo python3 cramc.py", "Für die vollständige Bereinigung mit sudo starten:  sudo python3 cramc.py", "Execute com sudo para limpeza completa:  sudo python3 cramc.py", "Для полной очистки запустите с sudo:  sudo python3 cramc.py", "شغّله باستخدام sudo لإجراء تنظيف كامل:  sudo python3 cramc.py", "使用 sudo 运行以进行完整清理：sudo python3 cramc.py", "完全にクリーンアップするには sudo で実行: sudo python3 cramc.py", "पूरी सफ़ाई के लिए sudo से चलाएँ: sudo python3 cramc.py")),
    ("Tam temizlik için programı Yönetici olarak çalıştırın", ("Tam temizlik için programı Yönetici olarak çalıştırın", "Run the app as Administrator for full cleanup", "Ejecuta la aplicación como administrador para una limpieza completa", "Exécutez l’application en tant qu’administrateur pour un nettoyage complet", "Starten Sie die App als Administrator für die vollständige Bereinigung", "Execute o aplicativo como Administrador para uma limpeza completa", "Запустите приложение от имени администратора для полной очистки", "شغّل التطبيق كمسؤول لإجراء تنظيف كامل", "以管理员身份运行应用以进行完整清理", "完全にクリーンアップするには管理者として実行してください", "पूरी सफ़ाई के लिए ऐप को व्यवस्थापक के रूप में चलाएँ")),
    ("psutil modülü bulunamadı; kaynak kodla çalıştırıyorsanız psutil kurun", ("psutil modülü bulunamadı; kaynak kodla çalıştırıyorsanız psutil kurun", "psutil module not found; install psutil when running from source", "No se encontró el módulo psutil; instálalo si ejecutas desde el código fuente", "Module psutil introuvable ; installez-le si vous exécutez depuis les sources", "psutil-Modul nicht gefunden; installieren Sie psutil bei Ausführung aus dem Quellcode", "Módulo psutil não encontrado; instale-o ao executar do código-fonte", "Модуль psutil не найден; установите psutil при запуске из исходников", "لم يتم العثور على وحدة psutil؛ ثبّتها عند التشغيل من المصدر", "未找到 psutil 模块；从源码运行时请安装 psutil", "psutil モジュールがありません。ソースから実行する場合は psutil をインストールしてください", "psutil मॉड्यूल नहीं मिला; स्रोत कोड से चलाने पर psutil इंस्टॉल करें")),
    ("ANLIK RAM KULLANIMI", ("ANLIK RAM KULLANIMI", "LIVE RAM USAGE", "USO DE RAM EN VIVO", "UTILISATION DE LA RAM EN DIRECT", "AKTUELLE RAM-NUTZUNG", "USO DE RAM AO VIVO", "ТЕКУЩЕЕ ИСПОЛЬЗОВАНИЕ RAM", "استخدام الذاكرة الآن", "实时内存使用情况", "リアルタイム RAM 使用量", "लाइव RAM उपयोग")),
    ("●  CANLI", ("●  CANLI", "●  LIVE", "●  EN VIVO", "●  EN DIRECT", "●  LIVE", "●  AO VIVO", "●  В РЕАЛЬНОМ ВРЕМЕНИ", "●  مباشر", "●  实时", "●  ライブ", "●  लाइव")),
    ("kullanılan", ("kullanılan", "used", "usada", "utilisée", "verwendet", "usada", "использовано", "مستخدمة", "已使用", "使用中", "उपयोग में")),
    ("TOPLAM", ("TOPLAM", "TOTAL", "TOTAL", "TOTAL", "GESAMT", "TOTAL", "ВСЕГО", "الإجمالي", "总计", "合計", "कुल")),
    ("KULLANILAN", ("KULLANILAN", "USED", "USADA", "UTILISÉE", "VERWENDET", "USADA", "ИСПОЛЬЗУЕТСЯ", "المستخدم", "已用", "使用量", "उपयोग किया गया")),
    ("KULLANILABİLİR", ("KULLANILABİLİR", "AVAILABLE", "DISPONIBLE", "DISPONIBLE", "VERFÜGBAR", "DISPONÍVEL", "ДОСТУПНО", "المتاح", "可用", "利用可能", "उपलब्ध")),
    ("ÖNBELLEK", ("ÖNBELLEK", "CACHE", "CACHÉ", "CACHE", "CACHE", "CACHE", "КЭШ", "ذاكرة التخزين المؤقت", "缓存", "キャッシュ", "कैश")),
    ("SİSTEM ÖZETİ", ("SİSTEM ÖZETİ", "SYSTEM OVERVIEW", "RESUMEN DEL SISTEMA", "APERÇU DU SYSTÈME", "SYSTEMÜBERSICHT", "VISÃO GERAL DO SISTEMA", "СВЕДЕНИЯ О СИСТЕМЕ", "ملخص النظام", "系统概览", "システム概要", "सिस्टम सारांश")),
    ("İŞLEM", ("İŞLEM", "PROCESSES", "PROCESOS", "PROCESSUS", "PROZESSE", "PROCESSOS", "ПРОЦЕССЫ", "العمليات", "进程", "プロセス", "प्रक्रियाएँ")),
    ("SON TEMİZLİK", ("SON TEMİZLİK", "LAST CLEANUP", "ÚLTIMA LIMPIEZA", "DERNIER NETTOYAGE", "LETZTE BEREINIGUNG", "ÚLTIMA LIMPEZA", "ПОСЛЕДНЯЯ ОЧИСТКА", "آخر تنظيف", "上次清理", "前回のクリーンアップ", "अंतिम सफ़ाई")),
    ("OTURUM", ("OTURUM", "SESSION", "SESIÓN", "SESSION", "SITZUNG", "SESSÃO", "СЕАНС", "الجلسة", "会话", "セッション", "सत्र")),
    ("TAHMİNİ KAZANÇ", ("TAHMİNİ KAZANÇ", "ESTIMATED GAIN", "GANANCIA ESTIMADA", "GAIN ESTIMÉ", "GESCHÄTZTER GEWINN", "GANHO ESTIMADO", "ОЦЕНКА ВЫИГРЫША", "المكسب المقدر", "预计释放量", "推定解放量", "अनुमानित लाभ")),
    ("●  CANLI HESAP", ("●  CANLI HESAP", "●  LIVE ESTIMATE", "●  CÁLCULO EN VIVO", "●  ESTIMATION EN DIRECT", "●  LIVE-BERECHNUNG", "●  CÁLCULO AO VIVO", "●  ТЕКУЩИЙ РАСЧЁТ", "●  تقدير مباشر", "●  实时估算", "●  リアルタイム計算", "●  लाइव अनुमान")),
    ("Kernel/process verilerinden hesaplanan aday havuzu üst sınırıdır; gerçek serbest kalan RAM daha düşük olabilir.", ("Kernel/process verilerinden hesaplanan aday havuzu üst sınırıdır; gerçek serbest kalan RAM daha düşük olabilir.", "This is an upper-bound estimate from kernel/process data; the actual freed RAM may be lower.", "Es un límite superior calculado con datos del kernel y procesos; la RAM realmente liberada puede ser menor.", "Il s’agit d’une estimation maximale basée sur le noyau et les processus ; la RAM réellement libérée peut être inférieure.", "Dies ist eine Obergrenze anhand von Kernel-/Prozessdaten; tatsächlich freigegebener RAM kann geringer sein.", "É um limite máximo calculado com dados do kernel/processos; a RAM realmente liberada pode ser menor.", "هذا تقدير للحد الأعلى بناءً على بيانات النواة والعمليات؛ وقد تكون الذاكرة المحررة فعلياً أقل.", "这是根据内核/进程数据计算的上限；实际释放的内存可能更少。", "カーネル／プロセス情報に基づく上限推定です。実際に解放される RAM は少ない場合があります。", "यह कर्नेल/प्रक्रिया डेटा पर आधारित ऊपरी अनुमान है; वास्तव में मुक्त RAM इससे कम हो सकती है।")),
    ("RAM TEMİZLE", ("RAM TEMİZLE", "CLEAN RAM", "LIMPIAR RAM", "NETTOYER LA RAM", "RAM BEREINIGEN", "LIMPAR RAM", "ОЧИСТИТЬ RAM", "تنظيف الذاكرة", "清理内存", "RAM をクリーンアップ", "RAM साफ़ करें")),
    ("⚙  TEMİZLİK SEÇENEKLERİ", ("⚙  TEMİZLİK SEÇENEKLERİ", "⚙  CLEANUP OPTIONS", "⚙  OPCIONES DE LIMPIEZA", "⚙  OPTIONS DE NETTOYAGE", "⚙  BEREINIGUNGSOPTIONEN", "⚙  OPÇÕES DE LIMPEZA", "⚙  ПАРАМЕТРЫ ОЧИСТКИ", "⚙  خيارات التنظيف", "⚙  清理选项", "⚙  クリーンアップ設定", "⚙  सफ़ाई विकल्प")),
    ("İŞLEM GÜNLÜĞÜ", ("İŞLEM GÜNLÜĞÜ", "ACTIVITY LOG", "REGISTRO DE ACTIVIDAD", "JOURNAL D’ACTIVITÉ", "AKTIVITÄTSPROTOKOLL", "LOG DE ATIVIDADES", "ЖУРНАЛ ОПЕРАЦИЙ", "سجل النشاط", "操作日志", "操作ログ", "गतिविधि लॉग")),
    ("TEMİZLE", ("TEMİZLE", "CLEAR", "BORRAR", "EFFACER", "LEEREN", "LIMPAR", "ОЧИСТИТЬ", "مسح", "清空", "クリア", "साफ़ करें")),
    ("Uygulama dili", ("Uygulama dili", "Application language", "Idioma de la aplicación", "Langue de l’application", "Anwendungssprache", "Idioma do aplicativo", "Язык приложения", "لغة التطبيق", "应用语言", "アプリの言語", "ऐप की भाषा")),
    ("PageCache (Sayfa Önbelleği)", ("PageCache (Sayfa Önbelleği)", "Page cache", "Caché de páginas", "Cache de pages", "Seiten-Cache", "Cache de páginas", "Кэш страниц", "ذاكرة الصفحات", "页面缓存", "ページキャッシュ", "पेज कैश")),
    ("Dosya içeriği önbelleği  •  drop_caches=1", ("Dosya içeriği önbelleği  •  drop_caches=1", "File content cache  •  drop_caches=1", "Caché del contenido de archivos  •  drop_caches=1", "Cache du contenu des fichiers  •  drop_caches=1", "Dateiinhalt-Cache  •  drop_caches=1", "Cache do conteúdo de arquivos  •  drop_caches=1", "ذاكرة محتوى الملفات  •  drop_caches=1", "文件内容缓存  •  drop_caches=1", "ファイル内容キャッシュ  •  drop_caches=1", "फ़ाइल सामग्री कैश  •  drop_caches=1")),
    ("Dentries & Inodes", ("Dentries & Inodes", "Dentries & inodes", "Dentries e inodos", "Dentries et inodes", "Dentries & Inodes", "Dentries e inodes", "Dentries и inodes", "Dentries و Inodes", "目录项与 inode", "Dentry と inode", "Dentries और Inodes")),
    ("Dizin/dosya yapısı önbelleği  •  drop_caches=2", ("Dizin/dosya yapısı önbelleği  •  drop_caches=2", "Directory/metadata cache  •  drop_caches=2", "Caché de directorios/metadatos  •  drop_caches=2", "Cache des répertoires/métadonnées  •  drop_caches=2", "Verzeichnis-/Metadaten-Cache  •  drop_caches=2", "Cache de diretórios/metadados  •  drop_caches=2", "Кэш каталогов/метаданных  •  drop_caches=2", "ذاكرة المجلدات والبيانات الوصفية  •  drop_caches=2", "目录/元数据缓存  •  drop_caches=2", "ディレクトリ／メタデータキャッシュ  •  drop_caches=2", "निर्देशिका/मेटाडेटा कैश  •  drop_caches=2")),
    ("Swap Sıfırlama", ("Swap Sıfırlama", "Reset swap", "Restablecer swap", "Réinitialiser le swap", "Swap zurücksetzen", "Redefinir swap", "Сбросить swap", "إعادة ضبط Swap", "重置交换空间", "Swap をリセット", "Swap रीसेट करें")),
    ("Swap'i RAM'e geri alıp yeniden açar  •  yavaş olabilir", ("Swap'i RAM'e geri alıp yeniden açar  •  yavaş olabilir", "Moves swap data back to RAM and re-enables it  •  may be slow", "Devuelve los datos de swap a la RAM y lo reactiva  •  puede tardar", "Ramène les données du swap en RAM et le réactive  •  peut être lent", "Verschiebt Swap-Daten zurück in den RAM und aktiviert ihn erneut  •  kann langsam sein", "Move os dados do swap de volta para a RAM e reativa  •  pode ser lento", "Возвращает данные из swap в RAM и включает его снова  •  может быть медленно", "يعيد بيانات Swap إلى الذاكرة ثم يفعّله مجدداً  •  قد يستغرق وقتاً", "将交换数据移回内存并重新启用  •  可能较慢", "Swap のデータを RAM に戻して再有効化します  •  時間がかかる場合があります", "Swap डेटा को RAM में वापस लाकर फिर सक्षम करता है  •  धीमा हो सकता है")),
    ("Önce sync çalıştır", ("Önce sync çalıştır", "Run sync first", "Ejecutar sync primero", "Exécuter sync d’abord", "Zuerst sync ausführen", "Executar sync primeiro", "Сначала выполнить sync", "شغّل sync أولاً", "先运行 sync", "先に sync を実行", "पहले sync चलाएँ")),
    ("Yazılmamış verileri diske yazar (önerilir)", ("Yazılmamış verileri diske yazar (önerilir)", "Writes pending data to disk (recommended)", "Escribe los datos pendientes en el disco (recomendado)", "Écrit les données en attente sur le disque (recommandé)", "Schreibt ausstehende Daten auf die Festplatte (empfohlen)", "Grava dados pendentes no disco (recomendado)", "Записывает ожидающие данные на диск (рекомендуется)", "يكتب البيانات المعلقة على القرص (موصى به)", "将待写入数据写入磁盘（推荐）", "未書き込みデータをディスクへ書き込みます（推奨）", "लंबित डेटा डिस्क पर लिखता है (अनुशंसित)")),
    ("Arka Plan Working Set", ("Arka Plan Working Set", "Background working set", "Conjunto de trabajo en segundo plano", "Ensemble de travail en arrière-plan", "Hintergrund-Working-Set", "Working set em segundo plano", "Рабочий набор фоновых процессов", "مجموعة العمل في الخلفية", "后台工作集", "バックグラウンド Working Set", "बैकग्राउंड वर्किंग सेट")),
    ("Süreçlerin kullanılmayan çalışma belleğini boşaltır", ("Süreçlerin kullanılmayan çalışma belleğini boşaltır", "Trims unused working memory from processes", "Libera memoria de trabajo no utilizada de los procesos", "Libère la mémoire de travail inutilisée des processus", "Gibt ungenutzten Arbeitsspeicher von Prozessen frei", "Libera memória de trabalho não utilizada dos processos", "Освобождает неиспользуемую рабочую память процессов", "يحرر ذاكرة العمل غير المستخدمة للعمليات", "释放进程未使用的工作内存", "プロセスの未使用ワーキングメモリを解放します", "प्रक्रियाओं की अप्रयुक्त कार्यशील मेमोरी मुक्त करता है")),
    ("Sistem Önbelleği", ("Sistem Önbelleği", "System cache", "Caché del sistema", "Cache système", "Systemcache", "Cache do sistema", "Системный кэш", "ذاكرة النظام المؤقتة", "系统缓存", "システムキャッシュ", "सिस्टम कैश")),
    ("Dosya sistemi önbelleğini küçültür  •  Yönetici gerekir", ("Dosya sistemi önbelleğini küçültür  •  Yönetici gerekir", "Trims the filesystem cache  •  administrator required", "Reduce la caché del sistema de archivos  •  requiere administrador", "Réduit le cache du système de fichiers  •  administrateur requis", "Verkleinert den Dateisystem-Cache  •  Administrator erforderlich", "Reduz o cache do sistema de arquivos  •  requer administrador", "Уменьшает кэш файловой системы  •  нужны права администратора", "缩减文件系统缓存  •  需要管理员权限", "ファイルシステムキャッシュを縮小  •  管理者権限が必要", "फ़ाइल सिस्टम कैश घटाता है  •  व्यवस्थापक आवश्यक")),
    ("OTOMATİK ZAMANLAYICI", ("OTOMATİK ZAMANLAYICI", "AUTOMATIC SCHEDULER", "PROGRAMADOR AUTOMÁTICO", "PLANIFICATEUR AUTOMATIQUE", "AUTOMATISCHER ZEITPLANER", "AGENDADOR AUTOMÁTICO", "АВТОМАТИЧЕСКИЙ ПЛАНИРОВЩИК", "الجدولة التلقائية", "自动计划", "自動スケジューラー", "स्वचालित शेड्यूलर")),
    ("Otomatik temizleme", ("Otomatik temizleme", "Automatic cleanup", "Limpieza automática", "Nettoyage automatique", "Automatische Bereinigung", "Limpeza automática", "Автоматическая очистка", "التنظيف التلقائي", "自动清理", "自動クリーンアップ", "स्वचालित सफ़ाई")),
    ("RAM kullanımı eşiği aşınca kendiliğinden temizler", ("RAM kullanımı eşiği aşınca kendiliğinden temizler", "Automatically cleans when RAM usage exceeds the threshold", "Limpia automáticamente cuando el uso de RAM supera el umbral", "Nettoie automatiquement lorsque l’utilisation de la RAM dépasse le seuil", "Bereinigt automatisch, wenn die RAM-Nutzung den Grenzwert überschreitet", "Limpa automaticamente quando o uso de RAM ultrapassa o limite", "Автоматически очищает, когда использование RAM превышает порог", "ينظف تلقائياً عند تجاوز استخدام الذاكرة الحد المحدد", "RAM 使用量がしきい値を超えると自動的にクリーンアップします", "RAM उपयोग सीमा पार होने पर अपने आप सफ़ाई करता है")),
    ("Kullanım eşiği", ("Kullanım eşiği", "Usage threshold", "Umbral de uso", "Seuil d’utilisation", "Nutzungsschwelle", "Limite de uso", "Порог использования", "حد الاستخدام", "使用阈值", "使用率のしきい値", "उपयोग सीमा")),
    ("Bekleme süresi", ("Bekleme süresi", "Cooldown", "Tiempo de espera", "Délai d’attente", "Wartezeit", "Tempo de espera", "Период ожидания", "مدة الانتظار", "冷却时间", "クールダウン", "प्रतीक्षा अवधि")),
    ("Yok", ("Yok", "None", "Ninguno", "Aucun", "Keine", "Nenhum", "Нет", "لا يوجد", "无", "なし", "कोई नहीं")),
    ("swap etkin değil", ("swap etkin değil", "swap is not enabled", "swap no está habilitado", "swap n’est pas activé", "Swap ist nicht aktiviert", "swap não está ativado", "swap не включён", "Swap غير مفعّل", "交换空间未启用", "swap は有効ではありません", "swap सक्षम नहीं है")),
    ("çalışan süreç", ("çalışan süreç", "running processes", "procesos en ejecución", "processus en cours", "laufende Prozesse", "processos em execução", "работающих процессов", "عملية قيد التشغيل", "个运行进程", "実行中のプロセス", "चल रही प्रक्रियाएँ")),
    ("Henüz yok", ("Henüz yok", "Not yet", "Todavía no", "Pas encore", "Noch nicht", "Ainda não", "Пока нет", "ليس بعد", "尚无", "まだありません", "अभी नहीं")),
    (" temizlik", (" temizlik", " cleanups", " limpiezas", " nettoyages", " Bereinigungen", " limpezas", " очисток", " عملية تنظيف", " 次清理", " 回クリーンアップ", " सफ़ाई")),
    ("seçenek seçilmedi", ("seçenek seçilmedi", "no option selected", "no se seleccionó ninguna opción", "aucune option sélectionnée", "keine Option ausgewählt", "nenhuma opção selecionada", "вариант не выбран", "لم يتم اختيار أي خيار", "未选择选项", "オプションが選択されていません", "कोई विकल्प नहीं चुना गया")),
    ("Sağdaki panelden en az bir temizlik seçeneği işaretleyin.", ("Sağdaki panelden en az bir temizlik seçeneği işaretleyin.", "Select at least one cleanup option in the panel on the right.", "Selecciona al menos una opción de limpieza en el panel de la derecha.", "Sélectionnez au moins une option de nettoyage dans le panneau de droite.", "Wählen Sie im rechten Bereich mindestens eine Bereinigungsoption aus.", "Selecione pelo menos uma opção de limpeza no painel à direita.", "Выберите хотя бы один вариант очистки на панели справа.", "حدد خيار تنظيف واحداً على الأقل في اللوحة اليمنى.", "右側のパネルで少なくとも 1 つのクリーンアップ項目を選択してください。", "दाईं ओर के पैनल में कम से कम एक सफ़ाई विकल्प चुनें。")),
    ("En az bir temizlik seçeneği seçin.", ("En az bir temizlik seçeneği seçin.", "Select at least one cleanup option.", "Selecciona al menos una opción de limpieza.", "Sélectionnez au moins une option de nettoyage.", "Wählen Sie mindestens eine Bereinigungsoption aus.", "Selecione pelo menos uma opção de limpeza.", "Выберите хотя бы один вариант очистки.", "请至少选择一个清理选项。", "少なくとも 1 つのクリーンアップ項目を選択してください。", "कम से कम एक सफ़ाई विकल्प चुनें。")),
    ("Temizlik için seçenek seçilmedi", ("Temizlik için seçenek seçilmedi", "No cleanup option selected", "No se seleccionó ninguna opción de limpieza", "Aucune option de nettoyage sélectionnée", "Keine Bereinigungsoption ausgewählt", "Nenhuma opção de limpeza selecionada", "Не выбран вариант очистки", "لم يتم اختيار خيار تنظيف", "未选择清理选项", "クリーンアップ項目が選択されていません", "सफ़ाई का कोई विकल्प नहीं चुना गया")),
    ("Root yetkisi yok: Tam temizlik için sudo ile çalıştırın", ("Root yetkisi yok: Tam temizlik için sudo ile çalıştırın", "No root access: run with sudo for full cleanup", "Sin acceso root: ejecuta con sudo para una limpieza completa", "Pas d’accès root : exécutez avec sudo pour un nettoyage complet", "Kein Root-Zugriff: für vollständige Bereinigung mit sudo starten", "Sem acesso root: execute com sudo para limpeza completa", "Нет root-доступа: запустите с sudo для полной очистки", "لا توجد صلاحيات root: شغّله باستخدام sudo للتنظيف الكامل", "没有 root 权限：使用 sudo 运行以进行完整清理", "root 権限がありません。完全なクリーンアップには sudo で実行してください", "root एक्सेस नहीं: पूरी सफ़ाई के लिए sudo से चलाएँ")),
    ("Otomatik temizleme için root yetkisi gerekli", ("Otomatik temizleme için root yetkisi gerekli", "Root access is required for automatic cleanup", "Se requiere acceso root para la limpieza automática", "L’accès root est requis pour le nettoyage automatique", "Für die automatische Bereinigung ist Root-Zugriff erforderlich", "É necessário acesso root para limpeza automática", "Для автоматической очистки требуется root-доступ", "يلزم الوصول إلى root للتنظيف التلقائي", "自动清理需要 root 权限", "自動クリーンアップには root 権限が必要です", "स्वचालित सफ़ाई के लिए root एक्सेस आवश्यक है")),
    ("TEMİZLENİYOR...", ("TEMİZLENİYOR...", "CLEANING...", "LIMPIANDO...", "NETTOYAGE...", "BEREINIGUNG...", "LIMPANDO...", "ОЧИСТКА...", "جارٍ التنظيف...", "正在清理…", "クリーンアップ中...", "सफ़ाई हो रही है...")),
    ("Temizlik sürüyor, lütfen bekleyin...", ("Temizlik sürüyor, lütfen bekleyin...", "Cleanup in progress, please wait...", "Limpieza en curso, espera...", "Nettoyage en cours, veuillez patienter...", "Bereinigung läuft, bitte warten...", "Limpeza em andamento, aguarde...", "Идёт очистка, подождите...", "التنظيف جارٍ، يرجى الانتظار...", "正在清理，请稍候…", "クリーンアップ中です。お待ちください...", "सफ़ाई जारी है, कृपया प्रतीक्षा करें...")),
    ("Temizlik tamamlanamadı", ("Temizlik tamamlanamadı", "Cleanup could not be completed", "No se pudo completar la limpieza", "Le nettoyage n’a pas pu être terminé", "Bereinigung konnte nicht abgeschlossen werden", "Não foi possível concluir a limpeza", "Не удалось завершить очистку", "تعذر إكمال التنظيف", "无法完成清理", "クリーンアップを完了できませんでした", "सफ़ाई पूरी नहीं हो सकी")),
    ("Beklenmeyen hata: ", ("Beklenmeyen hata: ", "Unexpected error: ", "Error inesperado: ", "Erreur inattendue : ", "Unerwarteter Fehler: ", "Erro inesperado: ", "Непредвиденная ошибка: ", "خطأ غير متوقع: ", "意外错误：", "予期しないエラー: ", "अनपेक्षित त्रुटि: ")),
    ("Swap sıfırlama sürüyor, bitmesini bekleyin.", ("Swap sıfırlama sürüyor, bitmesini bekleyin.", "Swap reset is in progress; wait for it to finish.", "El restablecimiento de swap está en curso; espera a que termine.", "La réinitialisation du swap est en cours ; attendez la fin.", "Swap wird zurückgesetzt; warten Sie, bis der Vorgang abgeschlossen ist.", "A redefinição do swap está em andamento; aguarde a conclusão.", "Идёт сброс swap; дождитесь завершения.", "إعادة ضبط Swap قيد التنفيذ؛ انتظر حتى تنتهي.", "正在重置交换空间，请等待完成。", "Swap のリセット中です。完了するまでお待ちください。", "Swap रीसेट हो रहा है; पूरा होने तक प्रतीक्षा करें।")),
    ("Depolama taraması/temizliği sürüyor; işlem bitince kapatın.", ("Depolama taraması/temizliği sürüyor; işlem bitince kapatın.", "Storage scan/cleanup is in progress; close the app when it finishes.", "El análisis/limpieza del almacenamiento está en curso; cierra la aplicación cuando termine.", "Analyse/nettoyage du stockage en cours ; fermez l’application une fois terminé.", "Speicherscan/-bereinigung läuft; schließen Sie die App nach Abschluss.", "A verificação/limpeza do armazenamento está em andamento; feche o app quando terminar.", "Идёт сканирование/очистка хранилища; закройте приложение после завершения.", "فحص/تنظيف التخزين جارٍ؛ أغلق التطبيق بعد الانتهاء.", "存储扫描/清理正在进行；完成后再关闭应用。", "ストレージのスキャン／クリーンアップ中です。完了後にアプリを閉じてください。", "स्टोरेज स्कैन/सफ़ाई जारी है; पूरा होने पर ऐप बंद करें।")),
    ("sn önce", ("sn önce", "sec ago", "s atrás", "s auparavant", "Sek. zuvor", "s atrás", "сек. назад", "ثانية مضت", "秒前", "秒前", "सेकंड पहले")),
    ("dk önce", ("dk önce", "min ago", "min atrás", "min auparavant", "Min. zuvor", "min atrás", "мин. назад", "دقيقة مضت", "分钟前", "分前", "मिनट पहले")),
    ("sa önce", ("sa önce", "hr ago", "h atrás", "h auparavant", "Std. zuvor", "h atrás", "ч назад", "ساعة مضت", "小时前", "時間前", "घंटे पहले")),
    ("gün önce", ("gün önce", "days ago", "días atrás", "jours auparavant", "Tage zuvor", "dias atrás", "дн. назад", "أيام مضت", "天前", "日前", "दिन पहले")),
    ("seçenek seçilmedi", ("seçenek seçilmedi", "no option selected", "no se seleccionó ninguna opción", "aucune option sélectionnée", "keine Option ausgewählt", "nenhuma opção selecionada", "вариант не выбран", "لم يتم اختيار أي خيار", "未选择选项", "オプションが選択されていません", "कोई विकल्प नहीं चुना गया")),
]
TRANSLATIONS = {language: {} for language in LANGUAGE_ORDER}
for _source, _values in I18N_ROWS:
    if len(_values) != len(LANGUAGE_ORDER):
        raise RuntimeError("Incomplete CRAMC translation row: " + _source)
    for _language, _translated in zip(LANGUAGE_ORDER, _values):
        TRANSLATIONS[_language][_source] = _translated


def _tr(value):
    """Translate known interface phrases; unknown diagnostic details stay untouched."""
    if not isinstance(value, str) or ACTIVE_LANGUAGE == "tr":
        return value
    table = TRANSLATIONS.get(ACTIVE_LANGUAGE, TRANSLATIONS["tr"])
    translated = value
    for source, target in sorted(table.items(), key=lambda item: len(item[0]), reverse=True):
        if source and source in translated:
            translated = translated.replace(source, target)
    return translated


def detect_system_language() -> str:
    """Use the desktop OS locale on first launch; manual choices are saved separately."""
    import locale
    aliases = {
        "turkish": "tr", "english": "en", "spanish": "es", "french": "fr",
        "german": "de", "portuguese": "pt", "russian": "ru", "arabic": "ar",
        "chinese": "zh", "japanese": "ja", "hindi": "hi",
    }
    candidates = []
    try:
        candidates.append(locale.getlocale()[0])
    except Exception:
        pass
    candidates.extend(os.environ.get(key) for key in ("LC_ALL", "LC_MESSAGES", "LANG"))
    for candidate in candidates:
        if not candidate:
            continue
        token = candidate.split(".", 1)[0].split("@", 1)[0].replace("-", "_")
        language = token.split("_", 1)[0].lower()
        language = aliases.get(language, language)
        if language in LANGUAGE_NAMES:
            return language
    return "tr"


def _translate_widget_tree(widget):
    """Translate existing Tk labels/buttons and special ttk tab/table captions."""
    if not TK_OK:
        return
    try:
        if isinstance(widget, ttk.Notebook):
            for tab_id in widget.tabs():
                caption = widget.tab(tab_id, "text")
                widget.tab(tab_id, text=_tr(caption))
        if isinstance(widget, ttk.Treeview):
            for column in widget["columns"]:
                caption = widget.heading(column, "text")
                widget.heading(column, text=_tr(caption))
        if "text" in widget.keys():
            caption = widget.cget("text")
            if caption:
                widget.configure(text=_tr(caption))
        if ACTIVE_LANGUAGE == "ar" and widget.winfo_class() == "Label":
            widget.configure(anchor="e", justify="right")
    except Exception:
        pass
    try:
        for child in widget.winfo_children():
            _translate_widget_tree(child)
    except Exception:
        pass


if TK_OK:
    # Dynamic label/button updates also pass through the same translator.
    _original_tk_configure = tk.Misc.configure
    if not getattr(_original_tk_configure, "_cramc_i18n", False):
        def _localized_tk_configure(self, cnf=None, **kwargs):
            if isinstance(cnf, dict) and "text" in cnf:
                cnf = dict(cnf)
                cnf["text"] = _tr(cnf["text"])
            if "text" in kwargs:
                kwargs["text"] = _tr(kwargs["text"])
            return _original_tk_configure(self, cnf, **kwargs)
        _localized_tk_configure._cramc_i18n = True
        tk.Misc.configure = _localized_tk_configure




# =========================================================================== #
#  YARDIMCILAR
# =========================================================================== #
def fmt_size(n: float) -> str:
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= GB:
        return f"{sign}{n / GB:.2f} GB"
    return f"{sign}{n / MB:.0f} MB"


def fmt_ago(ts: float) -> str:
    d = max(int(time.time() - ts), 0)
    if d < 60:
        return f"{d} sn önce"
    if d < 3600:
        return f"{d // 60} dk önce"
    if d < 86400:
        return f"{d // 3600} sa önce"
    return f"{d // 86400} gün önce"


def os_pretty() -> str:
    if IS_LINUX:
        try:
            return platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
        except Exception:
            pass
        try:
            with open("/etc/os-release", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        return "Linux"
    if IS_WINDOWS:
        return f"Windows {platform.release()}"
    return OS_NAME


def is_root_linux() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def is_admin_windows() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def has_privileges() -> bool:
    if IS_LINUX:
        return is_root_linux()
    if IS_WINDOWS:
        return is_admin_windows()
    return False


# =========================================================================== #
#  AYARLARIN KALICI SAKLANMASI
# =========================================================================== #
def config_dir() -> str:
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        home = os.path.expanduser("~")
        if is_root_linux() and os.environ.get("SUDO_USER"):
            try:
                import pwd
                home = pwd.getpwnam(os.environ["SUDO_USER"]).pw_dir
            except Exception:
                pass
        base = os.path.join(home, ".config")
    return os.path.join(base, "cramc")


def settings_path() -> str:
    return os.path.join(config_dir(), "settings.json")


def _chown_sudo_user(path: str):
    """sudo ile çalışırken oluşturulan dosyanın sahibini gerçek kullanıcı yap."""
    if IS_LINUX and is_root_linux() and os.environ.get("SUDO_UID"):
        try:
            uid = int(os.environ["SUDO_UID"])
            gid = int(os.environ.get("SUDO_GID", uid))
            os.chown(path, uid, gid)
        except (OSError, ValueError):
            pass


def load_settings() -> dict:
    try:
        with open(settings_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> bool:
    try:
        d = config_dir()
        os.makedirs(d, exist_ok=True)
        _chown_sudo_user(d)
        path = settings_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        _chown_sudo_user(path)
        return True
    except OSError:
        return False


# =========================================================================== #
#  BELLEK ÖLÇÜMÜ
# =========================================================================== #
@dataclass
class MemSnapshot:
    total: int
    used: int
    free: int          # Her iki platformda da kullanılabilir bellek (Linux MemAvailable)
    available: int
    cached: int        # Linux: buffers+cache | Windows: sistem önbelleği
    swap_total: int = 0
    swap_used: int = 0
    raw: dict = field(default_factory=dict)


def read_meminfo() -> dict:
    """/proc/meminfo içeriğini bayt cinsinden sözlük olarak döndürür."""
    info = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                try:
                    info[key.strip()] = int(parts[0]) * 1024
                except ValueError:
                    pass
    return info


def _snapshot_linux() -> MemSnapshot:
    """Linux belleğini MemAvailable temelinde ölçer.

    MemFree yalnızca tamamen boş sayfaları gösterir. MemAvailable ise kernel'in
    reclaim edilebilir cache/slab havuzlarını da hesaba katar ve günlük kullanım
    görünümü için daha gerçekçi bir used metriği sağlar.
    """
    m = read_meminfo()
    total = m["MemTotal"]
    free = m.get("MemFree", 0)
    buffers = m.get("Buffers", 0)
    shmem = m.get("Shmem", 0)
    cached_raw = m.get("Cached", 0)
    sreclaimable = m.get("SReclaimable", 0)
    fallback_available = free + buffers + max(cached_raw - shmem, 0) + sreclaimable
    available = min(total, max(0, m.get("MemAvailable", fallback_available)))
    used = max(total - available, 0)
    # Ekrandaki önbellek metriği tmpfs/shmem'i cache gibi göstermemek için çıkarır.
    cached = max(0, buffers + cached_raw - shmem + sreclaimable)
    swap_total = m.get("SwapTotal", 0)
    swap_used = max(swap_total - m.get("SwapFree", 0), 0)
    return MemSnapshot(total, used, available, available, cached,
                       swap_total, swap_used, m)


def _snapshot_windows() -> MemSnapshot:
    if psutil is None:
        raise RuntimeError("psutil bulunamadı (Windows derlemesinde psutil gömülü olmalıdır)")
    vm = psutil.virtual_memory()
    try:
        sw = psutil.swap_memory()
        swap_total, swap_used = sw.total, sw.used
    except Exception:
        swap_total = swap_used = 0
    perf = _win_perf_info()
    return MemSnapshot(vm.total, vm.used, vm.available, vm.available,
                       perf.get("system_cache", 0), swap_total, swap_used, perf)


def take_snapshot() -> MemSnapshot:
    if IS_LINUX:
        return _snapshot_linux()
    if IS_WINDOWS:
        return _snapshot_windows()
    raise RuntimeError(f"Desteklenmeyen işletim sistemi: {OS_NAME}")


def count_processes() -> int:
    try:
        if IS_LINUX:
            return sum(1 for n in os.listdir("/proc") if n.isdigit())
        if psutil is not None:
            return len(psutil.pids())
        return int(_win_perf_info().get("process_count", 0))
    except Exception:
        return 0


# =========================================================================== #
#  WINDOWS API (ctypes) - yalnızca Windows'ta ve ilk kullanımda yüklenir
# =========================================================================== #
_WINAPI = None


def _winapi():
    global _WINAPI
    if _WINAPI is not None:
        return _WINAPI

    import ctypes
    from ctypes import wintypes
    from types import SimpleNamespace

    class PERFORMANCE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("CommitTotal", ctypes.c_size_t),
            ("CommitLimit", ctypes.c_size_t),
            ("CommitPeak", ctypes.c_size_t),
            ("PhysicalTotal", ctypes.c_size_t),
            ("PhysicalAvailable", ctypes.c_size_t),
            ("SystemCache", ctypes.c_size_t),
            ("KernelTotal", ctypes.c_size_t),
            ("KernelPaged", ctypes.c_size_t),
            ("KernelNonpaged", ctypes.c_size_t),
            ("PageSize", ctypes.c_size_t),
            ("HandleCount", wintypes.DWORD),
            ("ProcessCount", wintypes.DWORD),
            ("ThreadCount", wintypes.DWORD),
        ]

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD),
                    ("Privileges", LUID_AND_ATTRIBUTES * 1)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetSystemFileCacheSize.argtypes = [ctypes.c_size_t, ctypes.c_size_t,
                                                wintypes.DWORD]
    kernel32.SetSystemFileCacheSize.restype = wintypes.BOOL

    psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    psapi.EmptyWorkingSet.restype = wintypes.BOOL
    psapi.GetPerformanceInfo.argtypes = [ctypes.POINTER(PERFORMANCE_INFORMATION),
                                         wintypes.DWORD]
    psapi.GetPerformanceInfo.restype = wintypes.BOOL

    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                               ctypes.POINTER(LUID)]
    advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
    advapi32.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL,
                                               ctypes.POINTER(TOKEN_PRIVILEGES),
                                               wintypes.DWORD, ctypes.c_void_p,
                                               ctypes.c_void_p]
    advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL

    _WINAPI = SimpleNamespace(
        ctypes=ctypes, wintypes=wintypes, kernel32=kernel32, psapi=psapi,
        advapi32=advapi32, PERFORMANCE_INFORMATION=PERFORMANCE_INFORMATION,
        LUID=LUID, TOKEN_PRIVILEGES=TOKEN_PRIVILEGES,
    )
    return _WINAPI


def _win_perf_info() -> dict:
    try:
        api = _winapi()
        pi = api.PERFORMANCE_INFORMATION()
        pi.cb = api.ctypes.sizeof(pi)
        if not api.psapi.GetPerformanceInfo(api.ctypes.byref(pi), pi.cb):
            return {}
        return {
            "system_cache": int(pi.SystemCache) * int(pi.PageSize),
            "process_count": int(pi.ProcessCount),
        }
    except Exception:
        return {}


def _win_enable_privilege(name: str) -> bool:
    """Geçerli işlem belirtecinde bir ayrıcalığı etkinleştirir."""
    try:
        api = _winapi()
        ct = api.ctypes
        token = api.wintypes.HANDLE()
        TOKEN_ADJUST_PRIVILEGES, TOKEN_QUERY = 0x0020, 0x0008
        if not api.advapi32.OpenProcessToken(
                api.kernel32.GetCurrentProcess(),
                TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ct.byref(token)):
            return False
        try:
            luid = api.LUID()
            if not api.advapi32.LookupPrivilegeValueW(None, name, ct.byref(luid)):
                return False
            tp = api.TOKEN_PRIVILEGES()
            tp.PrivilegeCount = 1
            tp.Privileges[0].Luid = luid
            tp.Privileges[0].Attributes = 0x00000002  # SE_PRIVILEGE_ENABLED
            ct.set_last_error(0)
            if not api.advapi32.AdjustTokenPrivileges(
                    token, False, ct.byref(tp), 0, None, None):
                return False
            return ct.get_last_error() == 0  # 1300 = ERROR_NOT_ALL_ASSIGNED
        finally:
            api.kernel32.CloseHandle(token)
    except Exception:
        return False


# =========================================================================== #
#  TEMİZLİK SEÇENEKLERİ VE TAHMİN
# =========================================================================== #
@dataclass
class CleanOptions:
    # Linux
    pagecache: bool = True
    dentries: bool = True
    swap_reset: bool = False
    sync_first: bool = True
    # Windows
    working_set: bool = True
    system_cache: bool = True

    def any_selected(self) -> bool:
        if IS_LINUX:
            return self.pagecache or self.dentries or self.swap_reset
        return self.working_set or self.system_cache


@dataclass
class SwapDev:
    name: str
    kind: str
    size: int
    used: int
    prio: int


def read_swaps() -> list:
    devs = []
    try:
        with open("/proc/swaps", "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()[1:]
    except OSError:
        return devs
    for line in lines:
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            devs.append(SwapDev(parts[0].replace("\\040", " "), parts[1],
                                int(parts[2]) * 1024, int(parts[3]) * 1024,
                                int(parts[4])))
        except ValueError:
            continue
    return devs


def swap_reset_is_safe(snap: MemSnapshot, swap_used: int) -> bool:
    """Swap içeriği RAM'e sığacak mı? (sistemi kilitlememek için güvenlik payı bırakılır)"""
    margin = max(256 * MB, int(snap.total * 0.10))
    return swap_used <= snap.available - margin


def estimate_gain(opts: CleanOptions, snap: MemSnapshot, ws_bytes: int = 0):
    """Kernel/işlem ölçümlerinden muhafazakâr aday havuzu tahmini döndürür.

    Sonuç garanti edilen boş RAM değildir. Linux'ta temiz page-cache adayları ve
    reclaimable slab üst sınırı; Windows'ta süreçlerin USS belleği ile kernel
    SystemCache metriği kullanılır. Çakışan Windows havuzları toplam RAM'i aşamaz.
    """
    items = []
    if IS_LINUX:
        m = snap.raw
        if opts.pagecache:
            cached = max(0, m.get("Cached", 0) + m.get("Buffers", 0)
                         - m.get("Shmem", 0))
            file_lru = m.get("Active(file)", 0) + m.get("Inactive(file)", 0)
            if file_lru > 0:
                cached = min(cached, file_lru)
            not_immediately_clean = (m.get("Mapped", 0) + m.get("Dirty", 0)
                                     + m.get("Writeback", 0))
            pagecache_candidate = max(0, cached - not_immediately_clean)
            items.append(("Temiz PageCache adayı (kernel meminfo)", pagecache_candidate))
        if opts.dentries:
            # SReclaimable tüm reclaimable slab havuzudur; tamamı dentry/inode
            # olarak boşaltılamayabileceğinden UI bunu açıkça üst sınır diye sunar.
            slab_candidate = max(0, m.get("SReclaimable", 0))
            items.append(("Reclaimable slab üst sınırı (SReclaimable)", slab_candidate))
        if opts.swap_reset:
            if snap.swap_total == 0:
                items.append(("Swap sıfırlama (swap etkin değil)", 0))
            elif snap.swap_used == 0:
                items.append(("Swap sıfırlama (swap boş)", 0))
            elif swap_reset_is_safe(snap, snap.swap_used):
                items.append(("Swap sıfırlama (RAM tüketimi)", -snap.swap_used))
            else:
                items.append(("Swap sıfırlama (RAM yetersiz, atlanır)", 0))
        positive = sum(max(value, 0) for _, value in items)
        # MemAvailable, kernel'in yakın vadede geri kazanabileceği alanı da
        # içerir; aday havuzunu kullanılan bellek sınırında tutar.
        ceiling = max(0, snap.total - snap.available)
        if positive > ceiling and positive:
            ratio = ceiling / positive
            items = [(label, int(value * ratio) if value > 0 else value)
                     for label, value in items]
    elif IS_WINDOWS:
        used_ceiling = max(0, snap.total - snap.available)
        if opts.working_set:
            private_ws = min(max(int(ws_bytes), 0), used_ceiling)
            items.append(("Süreç USS toplamı (özel bellek üst sınırı)", private_ws))
        else:
            private_ws = 0
        if opts.system_cache:
            # SystemCache, GetPerformanceInfo/psutil.snapshot üzerinden alınan
            # Windows kernel metriğidir. Working Set tahminiyle çakışmaya karşı cap.
            cache_candidate = min(max(int(snap.cached), 0),
                                  max(0, used_ceiling - private_ws))
            items.append(("Sistem dosya önbelleği (Windows SystemCache)", cache_candidate))
    return sum(value for _, value in items), items


# =========================================================================== #
#  DEPOLAMA / GEÇİCİ DOSYA TEMİZLİĞİ
# =========================================================================== #
TEMP_FILE_MIN_AGE_SECONDS = 24 * 60 * 60
TEMP_SCAN_LIMIT = 20000


@dataclass(frozen=True)
class TempFileCandidate:
    path: str
    size: int
    mtime: float


def _temp_target_uid():
    """sudo ile başlatıldıysa gerçek kullanıcıya ait geçici dosyaları hedefle."""
    if not IS_LINUX:
        return None
    try:
        return int(os.environ.get("SUDO_UID", os.getuid()))
    except (TypeError, ValueError, OSError):
        return os.getuid()


def _temp_roots() -> list:
    if IS_WINDOWS:
        roots = [tempfile.gettempdir()]
    elif IS_LINUX:
        roots = [tempfile.gettempdir(), "/tmp", "/var/tmp"]
    else:
        roots = []
    unique = []
    seen = set()
    for root in roots:
        path = os.path.abspath(os.path.expanduser(root))
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def _is_reparse_or_symlink(path: str, st) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    # Windows reparse points (junctions/mount points) are not followed.
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(IS_WINDOWS and (attrs & 0x400))  # FILE_ATTRIBUTE_REPARSE_POINT


def _path_is_inside(path: str, root: str) -> bool:
    try:
        path_abs = os.path.abspath(path)
        root_abs = os.path.abspath(root)
        return os.path.commonpath((path_abs, root_abs)) == root_abs and path_abs != root_abs
    except (ValueError, OSError):
        return False


def scan_temp_files(min_age_seconds: int = TEMP_FILE_MIN_AGE_SECONDS):
    """Yalnızca kullanıcı temp dizinlerinde 24 saatten eski normal dosyaları listeler.

    Sembolik bağlantılar/junction'lar izlenmez. Linux'ta SUDO_UID kullanılarak
    yalnızca gerçek kullanıcıya ait dosya ve dizinlere girilir. Hiçbir dosya silinmez.
    Dönüş: (adaylar, erişim_hatası_sayısı, limit_doldu_mu).
    """
    cutoff = time.time() - max(0, int(min_age_seconds))
    target_uid = _temp_target_uid()
    candidates = []
    errors = 0
    limited = False

    for root in _temp_roots():
        try:
            root_stat = os.lstat(root)
            if _is_reparse_or_symlink(root, root_stat) or not stat.S_ISDIR(root_stat.st_mode):
                continue
        except OSError:
            continue

        def on_walk_error(_exc):
            nonlocal errors
            errors += 1

        for current, dirnames, filenames in os.walk(
                root, topdown=True, followlinks=False, onerror=on_walk_error):
            try:
                current_stat = os.lstat(current)
            except OSError:
                dirnames[:] = []
                errors += 1
                continue
            if _is_reparse_or_symlink(current, current_stat):
                dirnames[:] = []
                continue
            if IS_LINUX and current != root and current_stat.st_uid != target_uid:
                # /tmp ve /var/tmp kökleri normalde root sahibidir; kök dizini
                # geçilebilir, ancak alt klasörler gerçek kullanıcıya ait olmalıdır.
                dirnames[:] = []
                continue

            safe_dirs = []
            for dirname in dirnames:
                child = os.path.join(current, dirname)
                try:
                    child_stat = os.lstat(child)
                except OSError:
                    errors += 1
                    continue
                if _is_reparse_or_symlink(child, child_stat) or not stat.S_ISDIR(child_stat.st_mode):
                    continue
                if IS_LINUX and child_stat.st_uid != target_uid:
                    continue
                safe_dirs.append(dirname)
            dirnames[:] = safe_dirs

            for filename in filenames:
                path = os.path.join(current, filename)
                try:
                    st = os.lstat(path)
                    if _is_reparse_or_symlink(path, st) or not stat.S_ISREG(st.st_mode):
                        continue
                    if IS_LINUX and st.st_uid != target_uid:
                        continue
                    if st.st_mtime > cutoff:
                        continue
                    candidates.append(TempFileCandidate(path, int(st.st_size), float(st.st_mtime)))
                    if len(candidates) >= TEMP_SCAN_LIMIT:
                        limited = True
                        break
                except OSError:
                    errors += 1
            if limited:
                break
        if limited:
            break

    candidates.sort(key=lambda item: item.size, reverse=True)
    return candidates, errors, limited


def delete_temp_files(candidates, min_age_seconds: int = TEMP_FILE_MIN_AGE_SECONDS):
    """Önizlemede listelenen dosyaları yeniden doğrulayıp tek tek siler.

    Yalnızca izin verilen temp köklerinin altında kalan, hâlâ normal dosya olan,
    eşik yaştan eski ve Linux'ta gerçek kullanıcıya ait dosyalar silinir.
    Dizinler, bağlantılar, cache klasörleri ve sistem genelindeki dosyalar silinmez.
    """
    cutoff = time.time() - max(0, int(min_age_seconds))
    target_uid = _temp_target_uid()
    roots = _temp_roots()
    removed = 0
    bytes_removed = 0
    skipped = 0

    for candidate in candidates:
        path = getattr(candidate, "path", "")
        root = next((r for r in roots if _path_is_inside(path, r)), None)
        if root is None:
            skipped += 1
            continue
        try:
            relative = os.path.relpath(path, root)
            parts = relative.split(os.sep)
            if not parts or any(part in ("", ".", "..") for part in parts):
                skipped += 1
                continue

            # POSIX'te dir_fd + O_NOFOLLOW parent symlink yarışlarını önler:
            # her klasör bileşeni gerçek dizin olarak açılır ve unlink aynı fd'de yapılır.
            if os.name == "posix" and hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd:
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
                dir_fd = os.open(root, flags)
                try:
                    for component in parts[:-1]:
                        next_fd = os.open(component, flags, dir_fd=dir_fd)
                        os.close(dir_fd)
                        dir_fd = next_fd
                    st = os.stat(parts[-1], dir_fd=dir_fd, follow_symlinks=False)
                    if not stat.S_ISREG(st.st_mode) or st.st_mtime > cutoff:
                        skipped += 1
                        continue
                    if IS_LINUX and st.st_uid != target_uid:
                        skipped += 1
                        continue
                    size = int(st.st_size)
                    os.unlink(parts[-1], dir_fd=dir_fd)
                finally:
                    os.close(dir_fd)
            else:
                # Windows: her üst dizin ve son dosya yeniden lstat edilir;
                # reparse point/junction veya symlink görüldüğünde işlem durur.
                parent = root
                safe = True
                for component in parts[:-1]:
                    parent = os.path.join(parent, component)
                    parent_stat = os.lstat(parent)
                    if (_is_reparse_or_symlink(parent, parent_stat)
                            or not stat.S_ISDIR(parent_stat.st_mode)):
                        safe = False
                        break
                if not safe:
                    skipped += 1
                    continue
                st = os.lstat(path)
                if (_is_reparse_or_symlink(path, st) or not stat.S_ISREG(st.st_mode)
                        or st.st_mtime > cutoff):
                    skipped += 1
                    continue
                size = int(st.st_size)
                os.remove(path)

            removed += 1
            bytes_removed += size
        except OSError:
            skipped += 1

    return removed, bytes_removed, skipped


# =========================================================================== #
#  TEMİZLİK MOTORU
# =========================================================================== #
def _find_cmd(name: str):
    path = shutil.which(name)
    if path:
        return path
    for d in ("/sbin", "/usr/sbin", "/bin", "/usr/bin"):
        cand = os.path.join(d, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _linux_swap_reset(log):
    """True: başarılı, False: hata, None: güvenlik nedeniyle atlandı."""
    devs = read_swaps()
    if not devs:
        log("warn", "Aktif swap bulunamadı, swap sıfırlama atlandı")
        return None
    used = sum(d.used for d in devs)
    snap = take_snapshot()
    if not swap_reset_is_safe(snap, used):
        log("warn", f"Swap sıfırlama atlandı: {fmt_size(used)} swap, mevcut boş RAM'e "
                    f"({fmt_size(snap.available)}) göre güvenli değil")
        return None
    swapoff, swapon = _find_cmd("swapoff"), _find_cmd("swapon")
    if not swapoff or not swapon:
        log("err", "swapoff/swapon komutları bulunamadı")
        return False

    log("info", f"Swap sıfırlanıyor: {len(devs)} aygıt, {fmt_size(used)} kullanımda "
                "(bu işlem biraz sürebilir)...")
    all_ok = True
    for d in devs:
        off_ok = False
        try:
            subprocess.run([swapoff, d.name], check=True, timeout=900,
                           capture_output=True, text=True)
            off_ok = True
        except subprocess.CalledProcessError as exc:
            log("err", f"swapoff {d.name} başarısız: {(exc.stderr or '').strip()}")
        except subprocess.TimeoutExpired:
            log("err", f"swapoff {d.name} zaman aşımına uğradı")
        except OSError as exc:
            log("err", f"swapoff çalıştırılamadı: {exc}")
        if not off_ok:
            all_ok = False
            continue
        cmd = [swapon] + (["-p", str(d.prio)] if d.prio >= 0 else []) + [d.name]
        try:
            subprocess.run(cmd, check=True, timeout=120, capture_output=True, text=True)
            log("ok", f"{d.name} yeniden etkinleştirildi")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            all_ok = False
            log("err", f"KRİTİK: {d.name} yeniden açılamadı ({exc}). "
                       f"Elle çalıştırın: sudo swapon {d.name}")
    return all_ok


def clean_linux(opts: CleanOptions, log):
    """(başarılı_mı, hata_mesajı) döndürür."""
    if not is_root_linux():
        log("err", "Root yetkisi yok: Tam temizlik için sudo ile çalıştırın")
        return False, "Tam temizlik için sudo ile çalıştırın"

    actions = 0
    last_err = ""

    if opts.sync_first:
        log("info", "Disk tamponları senkronize ediliyor (sync)...")
        try:
            subprocess.run(["sync"], check=True, timeout=180)
            log("ok", "sync tamamlandı")
        except FileNotFoundError:
            last_err = "'sync' komutu bulunamadı"
            log("err", last_err)
        except subprocess.TimeoutExpired:
            last_err = "'sync' zaman aşımına uğradı"
            log("err", last_err)
        except subprocess.CalledProcessError as exc:
            last_err = f"'sync' başarısız (kod {exc.returncode})"
            log("err", last_err)

    value = (1 if opts.pagecache else 0) | (2 if opts.dentries else 0)
    if value:
        names = " + ".join(n for n, on in (("PageCache", opts.pagecache),
                                           ("Dentries/Inodes", opts.dentries)) if on)
        try:
            with open(DROP_CACHES_PATH, "w", encoding="ascii") as fh:
                fh.write(f"{value}\n")
            actions += 1
            log("ok", f"drop_caches = {value} yazıldı ({names})")
        except PermissionError:
            last_err = "drop_caches yazma izni reddedildi"
            log("err", last_err)
        except OSError as exc:
            last_err = f"drop_caches yazılamadı: {exc}"
            log("err", last_err)

    if opts.swap_reset:
        result = _linux_swap_reset(log)
        if result:
            actions += 1
        elif result is False:
            last_err = "Swap sıfırlama başarısız (günlüğe bakın)"
        elif actions == 0:
            last_err = "Swap sıfırlama güvenlik nedeniyle atlandı"

    return actions > 0, last_err


def clean_windows(opts: CleanOptions, log):
    """(başarılı_mı, hata_mesajı) döndürür."""
    if psutil is None:
        log("err", "psutil bulunamadı:  pip install psutil")
        return False, "psutil gerekli (pip install psutil)"

    api = _winapi()
    ct = api.ctypes
    if not is_admin_windows():
        log("warn", "Yönetici yetkisi yok: yalnızca erişilebilen süreçler temizlenir")

    actions = 0
    last_err = ""

    if opts.working_set:
        PROCESS_QUERY_INFORMATION, PROCESS_SET_QUOTA = 0x0400, 0x0100
        ok = failed = 0
        own_pid = os.getpid()
        for proc in psutil.process_iter(["pid"]):
            pid = proc.info["pid"]
            if pid in (0, 4, own_pid):
                continue
            handle = api.kernel32.OpenProcess(
                PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
            if not handle:
                failed += 1
                continue
            try:
                if api.psapi.EmptyWorkingSet(handle):
                    ok += 1
                else:
                    failed += 1
            finally:
                api.kernel32.CloseHandle(handle)
        if ok:
            actions += 1
            log("ok", f"Working Set boşaltıldı: {ok} süreç ({failed} atlandı/erişilemedi)")
        else:
            last_err = "Hiçbir sürecin Working Set'i boşaltılamadı"
            log("err", last_err)

    if opts.system_cache:
        if not _win_enable_privilege("SeIncreaseQuotaPrivilege"):
            log("warn", "Sistem önbelleği atlandı: SeIncreaseQuotaPrivilege alınamadı "
                        "(Yönetici olarak çalıştırın)")
            if actions == 0:
                last_err = "Sistem önbelleği için Yönetici yetkisi gerekli"
        else:
            minus_one = ct.c_size_t(-1).value
            ct.set_last_error(0)
            if api.kernel32.SetSystemFileCacheSize(minus_one, minus_one, 0):
                actions += 1
                log("ok", "Sistem dosya önbelleği temizlendi")
            else:
                err = ct.get_last_error()
                last_err = f"SetSystemFileCacheSize başarısız (hata {err})"
                log("err", last_err)

    return actions > 0, last_err


# =========================================================================== #
#  VEKTÖREL LOGO (dışarıdan dosya gerekmez)
# =========================================================================== #
_C_BLUE = (47, 140, 255)
_C_GREEN = (46, 204, 113)
_C_DIE = (234, 255, 243)
_C_CHIP = (14, 19, 24)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _shield_halfwidth(v):
    top, shoulder, mid, tip = 0.03, 0.17, 0.46, 0.97
    if v < top or v > tip:
        return None
    if v < shoulder:
        return 0.40 * (v - top) / (shoulder - top)
    if v <= mid:
        return 0.40
    t = (v - mid) / (tip - mid)
    return 0.40 * (1.0 - t * t) ** 0.7


def _rrect(ax, ay, hx, hy, r):
    qx, qy = ax - (hx - r), ay - (hy - r)
    return max(qx, 0.0) ** 2 + max(qy, 0.0) ** 2 <= r * r


def _logo_sample(u, v):
    """Birim karede (u, v) noktasının rengi; saydamsa None."""
    dx, dy = u - 0.5, v - 0.47
    ax, ay = abs(dx), abs(dy)
    if ax <= 0.095 and ay <= 0.095:                      # çip kalıbı (die)
        return _C_DIE
    if ax <= 0.19 and ay <= 0.19 and _rrect(ax, ay, 0.19, 0.19, 0.045):  # çip gövdesi
        return _C_CHIP
    if 0.19 < ax <= 0.27 and abs(ay - 0.075) <= 0.028:   # yan bacaklar
        return _C_CHIP
    if 0.19 < ay <= 0.27 and abs(ax - 0.075) <= 0.028:   # üst/alt bacaklar
        return _C_CHIP
    hw = _shield_halfwidth(v)                            # kalkan
    if hw is None or abs(u - 0.5) > hw:
        return None
    t = min(max((u + v - 0.2) / 1.2, 0.0), 1.0)
    return _lerp(_C_BLUE, _C_GREEN, t)


def generate_logo_png(size: int, ss: int = 3) -> bytes:
    """Saf Python ile (kenar yumuşatmalı) logo PNG baytları üretir."""
    n = ss * ss
    rows = []
    for py in range(size):
        row = bytearray([0])  # PNG filtre baytı
        for px in range(size):
            r = g = b = a = 0
            for sy in range(ss):
                v = (py + (sy + 0.5) / ss) / size
                for sx in range(ss):
                    u = (px + (sx + 0.5) / ss) / size
                    c = _logo_sample(u, v)
                    if c:
                        r += c[0]
                        g += c[1]
                        b += c[2]
                        a += 1
            if a:
                row += bytes((r // a, g // a, b // a, a * 255 // n))
            else:
                row += b"\x00\x00\x00\x00"
        rows.append(bytes(row))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


# =========================================================================== #
#  ARAYÜZ SABİTLERİ
# =========================================================================== #
BG = "#121212"
CARD = "#1c1c1f"
CARD2 = "#232328"
CARD_BORDER = "#2a2a2f"
FG = "#e8e8ea"
FG_DIM = "#8b8b93"
BLUE = "#3b9cff"
GREEN = "#2ecc71"
GREEN_DARK = "#25a85c"
AMBER = "#f5a524"
RED = "#ef4444"
CYAN = "#22d3ee"

FONT = "DejaVu Sans" if IS_LINUX else "Segoe UI"
MONO = "DejaVu Sans Mono" if IS_LINUX else "Consolas"


def make_card(parent, title):
    """(dış_çerçeve, başlık_çubuğu, gövde) döndürür."""
    outer = tk.Frame(parent, bg=CARD, highlightbackground=CARD_BORDER,
                     highlightcolor=CARD_BORDER, highlightthickness=1)
    head = tk.Frame(outer, bg=CARD)
    head.pack(fill="x", padx=16, pady=(10, 4))
    tk.Label(head, text=title, bg=CARD, fg=FG_DIM,
             font=(FONT, 8, "bold")).pack(side="left")
    body = tk.Frame(outer, bg=CARD)
    body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
    return outer, head, body


def _round_rect(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


if TK_OK:
    class CheckRow(tk.Frame):
        """Koyu tema uyumlu, özel çizimli onay kutusu satırı."""

        def __init__(self, parent, text, desc, var, bg=CARD):
            super().__init__(parent, bg=bg, cursor="hand2")
            self.var = var
            self.box = tk.Canvas(self, width=20, height=20, bg=bg,
                                 highlightthickness=0, bd=0, cursor="hand2")
            self.box.grid(row=0, column=0, rowspan=2, padx=(0, 10), pady=2, sticky="n")
            self.title = tk.Label(self, text=text, bg=bg, fg=FG, anchor="w",
                                  justify="left", font=(FONT, 10, "bold"),
                                  cursor="hand2")
            self.title.grid(row=0, column=1, sticky="w")
            self.desc = tk.Label(self, text=desc, bg=bg, fg=FG_DIM, anchor="w",
                                 justify="left", wraplength=340, font=(FONT, 8),
                                 cursor="hand2")
            self.desc.grid(row=1, column=1, sticky="w")
            self.columnconfigure(1, weight=1)
            for w in (self, self.box, self.title, self.desc):
                w.bind("<Button-1>", self._toggle)
            var.trace_add("write", lambda *a: self._draw())
            self._draw()

        def _toggle(self, _event=None):
            self.var.set(not self.var.get())

        def _draw(self):
            c = self.box
            c.delete("all")
            on = bool(self.var.get())
            _round_rect(c, 1, 1, 19, 19, 5,
                        fill=BLUE if on else "#0d0d0f",
                        outline=BLUE if on else "#4a4a55")
            if on:
                c.create_line(5, 10, 9, 14, 15, 6, fill="#ffffff", width=2,
                              capstyle="round", joinstyle="round")

    class FlatSlider(tk.Canvas):
        """Koyu tema uyumlu yatay kaydırıcı (tamsayı değişkenine bağlı)."""

        def __init__(self, parent, var, lo, hi, step=1, bg=CARD):
            super().__init__(parent, height=22, bg=bg, highlightthickness=0,
                             bd=0, cursor="hand2")
            self.var, self.lo, self.hi, self.step = var, lo, hi, step
            self.bind("<Configure>", lambda e: self._draw())
            self.bind("<Button-1>", self._on_mouse)
            self.bind("<B1-Motion>", self._on_mouse)
            var.trace_add("write", lambda *a: self._draw())

        def _x_range(self):
            w = self.winfo_width()
            return 10, max(w - 10, 11)

        def _on_mouse(self, e):
            x0, x1 = self._x_range()
            f = (min(max(e.x, x0), x1) - x0) / (x1 - x0)
            val = self.lo + f * (self.hi - self.lo)
            val = round(val / self.step) * self.step
            self.var.set(int(min(max(val, self.lo), self.hi)))

        def _draw(self):
            self.delete("all")
            x0, x1 = self._x_range()
            cy = 11
            try:
                f = (self.var.get() - self.lo) / (self.hi - self.lo)
            except Exception:
                f = 0
            f = min(max(f, 0.0), 1.0)
            xk = x0 + f * (x1 - x0)
            self.create_line(x0, cy, x1, cy, fill="#2f2f36", width=4, capstyle="round")
            self.create_line(x0, cy, xk, cy, fill=BLUE, width=4, capstyle="round")
            self.create_oval(xk - 8, cy - 8, xk + 8, cy + 8, fill="#ffffff",
                             outline=BLUE, width=2)

    class GhostButton(tk.Label):
        def __init__(self, parent, text, command, bg=CARD):
            super().__init__(parent, text=text, bg=bg, fg=FG_DIM, cursor="hand2",
                             font=(FONT, 8, "bold"), padx=6, pady=2)
            self._cmd = command
            self.bind("<Button-1>", lambda e: self._cmd())
            self.bind("<Enter>", lambda e: self.configure(fg=FG))
            self.bind("<Leave>", lambda e: self.configure(fg=FG_DIM))


# =========================================================================== #
#  ANA UYGULAMA
# =========================================================================== #
class CramcApp:
    def __init__(self, root):
        global ACTIVE_LANGUAGE
        self.root = root
        self.busy = False
        self.q = queue.Queue()
        self.ws_bytes = 0  # Windows: toplam süreç USS (özel, benzersiz bellek)
        self.storage_candidates = []
        self.storage_busy = False
        self._stop = False
        self._swap_running = False
        self._notice_job = None
        self._save_job = None
        self._last_snap = None
        self._last_tick_err = None
        self._warned_auto = False
        self.last_auto_ts = 0.0
        self.session_freed = 0
        self.session_cleans = 0
        self._icons = []
        self.logo_img = None
        self._slider_trace_ids = []

        s = load_settings()
        saved_language = s.get("language")
        self.language = saved_language if saved_language in LANGUAGE_NAMES else detect_system_language()
        ACTIVE_LANGUAGE = self.language
        o = s.get("opts", {}) if isinstance(s.get("opts"), dict) else {}
        defaults = CleanOptions()

        def bv(name):
            return tk.BooleanVar(value=bool(o.get(name, getattr(defaults, name))))

        def iv(key, default, lo, hi):
            try:
                return tk.IntVar(value=min(max(int(s.get(key, default)), lo), hi))
            except (TypeError, ValueError):
                return tk.IntVar(value=default)

        self.v_pagecache = bv("pagecache")
        self.v_dentries = bv("dentries")
        self.v_swap = bv("swap_reset")
        self.v_sync = bv("sync_first")
        self.v_ws = bv("working_set")
        self.v_syscache = bv("system_cache")
        self.v_auto = tk.BooleanVar(value=bool(s.get("auto_enabled", False)))
        self.v_thr = iv("auto_threshold", 85, 50, 95)
        self.v_cd = iv("auto_cooldown", 10, 1, 60)
        self.settings_open = bool(s.get("settings_open", True))
        ts = s.get("last_clean_ts")
        self.last_clean_ts = float(ts) if isinstance(ts, (int, float)) else None

        root.title(f"{APP_NAME} ({APP_SHORT})")
        root.configure(bg=BG)
        self._load_icons()
        self._build_style()
        self._build_ui()
        self._wire_traces()
        self._fit_window()
        self._log_startup()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        if IS_WINDOWS and psutil is not None:
            threading.Thread(target=self._ws_loop, daemon=True).start()
        self._tick()
        self._poll_queue()

    # ------------------------------------------------------------- ikonlar
    def _load_icons(self):
        try:
            imgs = []
            for size in (64, 32):
                data = base64.b64encode(generate_logo_png(size)).decode("ascii")
                imgs.append(tk.PhotoImage(data=data))
            self.logo_img = tk.PhotoImage(
                data=base64.b64encode(generate_logo_png(52)).decode("ascii"))
            self._icons = imgs + [self.logo_img]
            self.root.iconphoto(True, *imgs)
        except Exception:
            self.logo_img = None  # logo olmadan da çalışır

    # --------------------------------------------------------------- stil
    def _build_style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Ram.Horizontal.TProgressbar", troughcolor="#2a2a2f",
                     background=BLUE, bordercolor=CARD, lightcolor=BLUE,
                     darkcolor=BLUE, thickness=16)
        st.configure("Swap.Horizontal.TProgressbar", troughcolor="#33333a",
                     background=CYAN, bordercolor=CARD2, lightcolor=CYAN,
                     darkcolor=CYAN, thickness=6)
        st.configure("Busy.Horizontal.TProgressbar", troughcolor=BG,
                     background=GREEN, bordercolor=BG, lightcolor=GREEN,
                     darkcolor=GREEN, thickness=4)
        st.configure("Dark.Vertical.TScrollbar", background="#2f2f36",
                     troughcolor="#0d0d0f", bordercolor="#0d0d0f",
                     arrowcolor=FG_DIM, lightcolor="#2f2f36", darkcolor="#2f2f36",
                     relief="flat")
        st.map("Dark.Vertical.TScrollbar", background=[("active", "#3d3d46")])
        st.configure("CRAMC.TNotebook", background=BG, borderwidth=0)
        st.configure("CRAMC.TNotebook.Tab", background=CARD2, foreground=FG_DIM,
                     padding=(18, 10), borderwidth=0)
        st.map("CRAMC.TNotebook.Tab",
               background=[("selected", CARD)],
               foreground=[("selected", FG), ("active", FG)])
        st.configure("Storage.Treeview", background="#0d0d0f", foreground=FG,
                     fieldbackground="#0d0d0f", rowheight=26, borderwidth=0)
        st.configure("Storage.Treeview.Heading", background=CARD2,
                     foreground=FG_DIM, relief="flat")
        st.map("Storage.Treeview", background=[("selected", "#21436a")],
               foreground=[("selected", "#ffffff")])
        self.style = st

    # ----------------------------------------------------------------- UI
    def _build_ui(self):
        self.notebook = ttk.Notebook(self.root, style="CRAMC.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=12, pady=12)

        self.welcome_tab = tk.Frame(self.notebook, bg=BG)
        self.ram_tab = tk.Frame(self.notebook, bg=BG)
        self.storage_tab = tk.Frame(self.notebook, bg=BG)

        self.notebook.add(self.welcome_tab, text="✦  Hoş Geldin")
        self.notebook.add(self.ram_tab, text="◈  RAM Yönetimi")
        self.notebook.add(self.storage_tab, text="▣  Depolama")

        self._build_welcome_tab(self.welcome_tab)
        self._build_dashboard_tab(self.ram_tab)
        self._build_storage_tab(self.storage_tab)
        _translate_widget_tree(self.root)

    def _build_welcome_tab(self, parent):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="both", expand=True, padx=24, pady=22)

        hero = tk.Frame(outer, bg=CARD, highlightbackground=CARD_BORDER,
                        highlightthickness=1)
        hero.pack(fill="x", pady=(0, 14))

        head = tk.Frame(hero, bg=CARD)
        head.pack(fill="x", padx=24, pady=(22, 6))
        if self.logo_img is not None:
            tk.Label(head, image=self.logo_img, bg=CARD).pack(side="left", padx=(0, 14))
        title_box = tk.Frame(head, bg=CARD)
        title_box.pack(side="left", fill="x", expand=True)
        tk.Label(title_box, text="CRAMC'ye hoş geldin!", bg=CARD, fg=FG,
                 font=(FONT, 22, "bold")).pack(anchor="w")
        tk.Label(title_box, text=f"{os_pretty()}  •  Sürüm {APP_VERSION}",
                 bg=CARD, fg=BLUE, font=(FONT, 9, "bold")).pack(anchor="w", pady=(3, 0))

        tk.Label(hero,
                 text="ComputerRAMCleaner; RAM ve sistem önbelleği durumunu izlemenize, "
                      "işletim sisteminize uygun temizlik işlemlerini seçmenize ve "
                      "kullanıcı geçici dosyalarını kontrollü biçimde yönetmenize yardımcı olur.",
                 bg=CARD, fg=FG_DIM, justify="left", anchor="w", wraplength=900,
                 font=(FONT, 10), padx=24).pack(fill="x", pady=(8, 12))

        action_row = tk.Frame(hero, bg=CARD)
        action_row.pack(fill="x", padx=24, pady=(0, 22))
        tk.Button(action_row, text="RAM Yönetimine Git  →",
                  command=lambda: self.notebook.select(self.ram_tab),
                  bg=GREEN, fg="#06220f", activebackground=GREEN_DARK,
                  relief="flat", bd=0, cursor="hand2",
                  font=(FONT, 10, "bold"), padx=18, pady=9).pack(side="left")
        privilege_text = ("● Yetkili çalışıyor" if has_privileges()
                          else ("● Linux: tam temizlik için sudo gerekli" if IS_LINUX
                                else "● Yönetici izni yok; bazı işlemler atlanabilir"))
        privilege_color = GREEN if has_privileges() else AMBER
        tk.Label(action_row, text=privilege_text, bg=CARD, fg=privilege_color,
                 font=(FONT, 9, "bold")).pack(side="right", padx=(10, 0))

        tk.Label(outer, text="HIZLI BAŞLANGIÇ REHBERİ", bg=BG, fg=FG_DIM,
                 font=(FONT, 9, "bold")).pack(anchor="w", pady=(8, 10))

        guide = tk.Frame(outer, bg=BG)
        guide.pack(fill="x")
        for col in range(3):
            guide.columnconfigure(col, weight=1, uniform="guide")

        guide_items = [
            ("01", "Sistemi gözlemle",
             "RAM, kullanılabilir bellek, önbellek, swap ve işlem sayısını RAM Yönetimi sekmesinde incele."),
            ("02", "İşlemleri seç",
             "Linux veya Windows için gösterilen seçenekleri ihtiyacına göre işaretle. Swap sıfırlama isteğe bağlıdır."),
            ("03", "Önizle ve uygula",
             "Tahmini kazanımı üst sınır olarak değerlendir; ardından RAM TEMİZLE düğmesiyle işlemi başlat."),
        ]
        for col, (num, title_text, desc) in enumerate(guide_items):
            card = tk.Frame(guide, bg=CARD, highlightbackground=CARD_BORDER,
                            highlightthickness=1)
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 7, 0),
                      pady=0)
            tk.Label(card, text=num, bg=CARD, fg=BLUE,
                     font=(FONT, 10, "bold")).pack(anchor="w", padx=16, pady=(15, 4))
            tk.Label(card, text=title_text, bg=CARD, fg=FG,
                     font=(FONT, 11, "bold")).pack(anchor="w", padx=16)
            tk.Label(card, text=desc, bg=CARD, fg=FG_DIM, justify="left",
                     anchor="nw", wraplength=260, font=(FONT, 8)).pack(
                         fill="both", expand=True, padx=16, pady=(7, 16))

        note = tk.Frame(outer, bg="#2b2418", highlightbackground="#5a4528",
                        highlightthickness=1)
        note.pack(fill="x", pady=(16, 0))
        tk.Label(note,
                 text="GÜVENLİK NOTU  •  Bellek önbelleklerini temizlemek her zaman performans artışı sağlamaz. "
                      "Sistemler bu belleği ihtiyaç olduğunda otomatik geri kazanabilir. Depolama sekmesi "
                      "yalnızca kullanıcının geçici klasörlerinde 24 saatten eski dosyaları listeler; "
                      "silmeden önce önizleme ve onay ister.",
                 bg="#2b2418", fg=AMBER, justify="left", anchor="w",
                 wraplength=920, font=(FONT, 8), padx=15, pady=11).pack(fill="x")

    def _build_dashboard_tab(self, tab):
        main = tk.Frame(tab, bg=BG)
        main.pack(fill="both", expand=True, padx=20, pady=(16, 8))
        main.columnconfigure(0, weight=1, uniform="cols")
        main.columnconfigure(1, weight=1, uniform="cols")
        main.rowconfigure(2, weight=1)

        self._build_header(main)
        self._build_banner(main)

        left = tk.Frame(main, bg=BG)
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        right = tk.Frame(main, bg=BG)
        right.grid(row=2, column=1, sticky="nsew", padx=(8, 0))
        self._build_left(left)
        self._build_right(right)

        tk.Label(main, text=f"{APP_SHORT} v{APP_VERSION}", bg=BG, fg="#4a4a52",
                 font=(FONT, 8)).grid(row=3, column=0, columnspan=2, pady=(6, 0))

    def _build_storage_tab(self, parent):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="both", expand=True, padx=22, pady=20)

        tk.Label(outer, text="DEPOLAMA YÖNETİMİ", bg=BG, fg=BLUE,
                 font=(FONT, 9, "bold")).pack(anchor="w")
        tk.Label(outer, text="Geçici dosyaları güvenle gözden geçir",
                 bg=BG, fg=FG, font=(FONT, 20, "bold")).pack(anchor="w", pady=(4, 5))
        tk.Label(outer,
                 text="CRAMC yalnızca kullanıcı geçici klasörlerini tarar. Varsayılan olarak "
                      "24 saatten eski normal dosyalar listelenir; sistem klasörleri, tarayıcı "
                      "önbellekleri, İndirilenler klasörü ve sembolik bağlantı hedefleri taranmaz.",
                 bg=BG, fg=FG_DIM, justify="left", anchor="w", wraplength=950,
                 font=(FONT, 9)).pack(fill="x", pady=(0, 14))

        summary = tk.Frame(outer, bg=CARD, highlightbackground=CARD_BORDER,
                           highlightthickness=1)
        summary.pack(fill="x", pady=(0, 12))
        self.storage_status = tk.Label(summary,
            text="Tarama yapılmadı. Önce geçici dosyaları tara.", bg=CARD,
            fg=FG_DIM, anchor="w", justify="left", wraplength=900,
            font=(FONT, 10), padx=16, pady=13)
        self.storage_status.pack(fill="x")

        table_frame = tk.Frame(outer, bg=CARD, highlightbackground=CARD_BORDER,
                               highlightthickness=1)
        table_frame.pack(fill="both", expand=True)
        columns = ("path", "size", "date")
        self.storage_tree = ttk.Treeview(table_frame, columns=columns,
            show="headings", style="Storage.Treeview", height=12)
        self.storage_tree.heading("path", text="GEÇİCİ DOSYA")
        self.storage_tree.heading("size", text="BOYUT")
        self.storage_tree.heading("date", text="SON DEĞİŞİKLİK")
        self.storage_tree.column("path", width=650, minwidth=240, anchor="w")
        self.storage_tree.column("size", width=110, minwidth=90, anchor="e")
        self.storage_tree.column("date", width=170, minwidth=140, anchor="center")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical",
                                  command=self.storage_tree.yview,
                                  style="Dark.Vertical.TScrollbar")
        self.storage_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.storage_tree.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        buttons = tk.Frame(outer, bg=BG)
        buttons.pack(fill="x", pady=(12, 0))
        self.storage_scan_button = tk.Button(
            buttons, text="GEÇİCİ DOSYALARI TARA", command=self._scan_storage,
            bg=BLUE, fg="#061321", activebackground="#287ed2",
            relief="flat", bd=0, cursor="hand2", font=(FONT, 10, "bold"),
            padx=18, pady=10)
        self.storage_scan_button.pack(side="left")
        self.storage_clean_button = tk.Button(
            buttons, text="ÖNİZLEMEDEKİ DOSYALARI SİL", command=self._clean_storage,
            bg=GREEN, fg="#06220f", activebackground=GREEN_DARK,
            disabledforeground="#557767", relief="flat", bd=0, cursor="hand2",
            font=(FONT, 10, "bold"), padx=18, pady=10, state="disabled")
        self.storage_clean_button.pack(side="left", padx=(10, 0))
        tk.Label(buttons, text="Yalnızca listelenen dosyalar silinir; onay gerekir.",
                 bg=BG, fg=FG_DIM, font=(FONT, 8)).pack(side="right")

    def _scan_storage(self):
        if self.storage_busy:
            return
        self.storage_busy = True
        # Yeni tarama başlarken önceki önizlemenin yanlışlıkla silinmesini önle.
        self.storage_candidates = []
        for item in self.storage_tree.get_children():
            self.storage_tree.delete(item)
        self.storage_scan_button.configure(state="disabled")
        self.storage_clean_button.configure(state="disabled")
        self.storage_status.configure(text="Geçici klasörler taranıyor…", fg=BLUE)
        threading.Thread(target=self._storage_scan_worker, daemon=True).start()

    def _storage_scan_worker(self):
        try:
            candidates, errors, limited = scan_temp_files()
            self.q.put(("storage_scan_done", candidates, errors, limited))
        except Exception as exc:
            self.q.put(("storage_scan_error", str(exc)))

    def _clean_storage(self):
        if self.storage_busy or not self.storage_candidates:
            return
        count = len(self.storage_candidates)
        total_bytes = sum(item.size for item in self.storage_candidates)
        answer = messagebox.askyesno(
            _tr("Geçici dosyaları sil"),
            _tr(f"{count} adet, toplam {fmt_size(total_bytes)} boyutunda geçici dosya silinecek.\n\n"
            "Yalnızca kullanıcı geçici klasörlerinde bulunan ve en az 24 saat önce değiştirilmiş "
            "normal dosyalar hedeflenir. Açık/kilitli veya artık uygun olmayan dosyalar atlanır.\n\n"
            "Devam etmek istiyor musunuz?"),
            parent=self.root)
        if not answer:
            return
        self.storage_busy = True
        self.storage_scan_button.configure(state="disabled")
        self.storage_clean_button.configure(state="disabled")
        self.storage_status.configure(text="Önizlemede listelenen dosyalar tekrar doğrulanıyor ve temizleniyor…",
                                      fg=AMBER)
        candidates = list(self.storage_candidates)
        threading.Thread(target=self._storage_clean_worker,
                         args=(candidates,), daemon=True).start()

    def _storage_clean_worker(self, candidates):
        try:
            removed, freed, skipped = delete_temp_files(candidates)
            self.q.put(("storage_clean_done", removed, freed, skipped))
        except Exception as exc:
            self.q.put(("storage_clean_error", str(exc)))

    def _finish_storage_scan(self, candidates, errors, limited):
        self.storage_busy = False
        # Silme işlemi yalnızca tabloda görünür olan önizleme satırlarını kapsar.
        # Tarama 1000'den fazla dosya bulursa diğerleri kullanıcıya gösterilmeden silinmez.
        self.storage_candidates = list(candidates[:1000])
        for item in self.storage_tree.get_children():
            self.storage_tree.delete(item)
        total_bytes = sum(item.size for item in candidates)
        for item in candidates[:1000]:
            self.storage_tree.insert("", "end", values=(
                item.path, fmt_size(item.size),
                datetime.fromtimestamp(item.mtime).strftime("%d.%m.%Y %H:%M")))
        shown = min(len(candidates), 1000)
        text = (f"Bulunan dosya: {len(candidates)}  •  Toplam boyut: {fmt_size(total_bytes)}  •  "
                f"Yaş eşiği: 24 saat")
        if shown < len(candidates):
            text += f"  •  İlk {shown} dosya gösteriliyor ve yalnızca bunlar silme önizlemesine dahil"
        if limited:
            text += "  •  Güvenlik sınırı nedeniyle tarama 20.000 dosyada durdu"
        if errors:
            text += f"  •  Erişim/okuma hatası: {errors}"
        if not candidates:
            text = "Uygun geçici dosya bulunamadı. Sistem ve kullanıcı klasörleri korunmuştur."
        self.storage_status.configure(text=text, fg=GREEN if candidates else FG_DIM)
        self.storage_scan_button.configure(state="normal")
        self.storage_clean_button.configure(
            state="normal" if self.storage_candidates else "disabled")

    def _finish_storage_clean(self, removed, freed, skipped):
        self.storage_busy = False
        self.log("ok", f"Depolama temizliği: {removed} dosya, {fmt_size(freed)} silindi; {skipped} dosya atlandı")
        self.storage_status.configure(
            text=f"Temizlik tamamlandı: {removed} dosya silindi ({fmt_size(freed)}). "
                 f"Atlanan dosya: {skipped}. Son durumu görmek için yeniden tarayın.",
            fg=GREEN)
        self.storage_candidates = []
        for item in self.storage_tree.get_children():
            self.storage_tree.delete(item)
        self.storage_scan_button.configure(state="normal")
        self.storage_clean_button.configure(state="disabled")

    def _finish_storage_error(self, message):
        self.storage_busy = False
        self.storage_status.configure(text=f"Depolama işlemi başarısız: {message}", fg=RED)
        self.storage_scan_button.configure(state="normal")
        self.storage_clean_button.configure(
            state="normal" if self.storage_candidates else "disabled")

    def _build_header(self, main):
        hdr = tk.Frame(main, bg=BG)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        if self.logo_img is not None:
            tk.Label(hdr, image=self.logo_img, bg=BG).pack(side="left", padx=(0, 12))
        tb = tk.Frame(hdr, bg=BG)
        tb.pack(side="left")
        tk.Label(tb, text=f"{APP_NAME} ({APP_SHORT})", bg=BG, fg=FG,
                 font=(FONT, 17, "bold")).pack(anchor="w")
        tk.Label(tb, text=f"{os_pretty()}  •  RAM Temizleme ve Optimizasyon Aracı",
                 bg=BG, fg=FG_DIM, font=(FONT, 9)).pack(anchor="w")

        if has_privileges():
            text = "●  ROOT YETKİSİ" if IS_LINUX else "●  YÖNETİCİ"
            bg, fg = "#10331f", GREEN
        else:
            text = "●  SUDO YOK" if IS_LINUX else "●  STANDART KULLANICI"
            bg, fg = "#3a2a0a", AMBER
        tk.Label(hdr, text=text, bg=bg, fg=fg, font=(FONT, 9, "bold"),
                 padx=12, pady=5).pack(side="right")

    def _build_banner(self, main):
        self.banner = tk.Label(main, text="", bg="#3a2a0a", fg=AMBER, anchor="w",
                               justify="left", font=(FONT, 10, "bold"),
                               padx=12, pady=7, wraplength=800)
        self.banner.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self._refresh_banner()

    def _refresh_banner(self):
        msgs = []
        if IS_LINUX and not is_root_linux():
            msgs.append("Tam temizlik için sudo ile çalıştırın:  sudo python3 cramc.py")
        elif IS_WINDOWS and not is_admin_windows():
            msgs.append("Tam temizlik için programı Yönetici olarak çalıştırın")
        if IS_WINDOWS and psutil is None:
            msgs.append("psutil modülü bulunamadı; kaynak kodla çalıştırıyorsanız psutil kurun")
        if msgs:
            self.banner.configure(text="⚠  " + "\n⚠  ".join(msgs))
            self.banner.grid()
        else:
            self.banner.grid_remove()

    # ---- sol sütun
    def _build_left(self, parent):
        # Canlı RAM kartı
        card, head, body = make_card(parent, "ANLIK RAM KULLANIMI")
        card.pack(fill="x", pady=(0, 8))
        tk.Label(head, text="●  CANLI", bg=CARD, fg=GREEN,
                 font=(FONT, 8, "bold")).pack(side="right")
        top = tk.Frame(body, bg=CARD)
        top.pack(fill="x")
        self.pct_label = tk.Label(top, text="0%", bg=CARD, fg=FG,
                                  font=(FONT, 30, "bold"))
        self.pct_label.pack(side="left")
        tk.Label(top, text="kullanılan", bg=CARD, fg=FG_DIM,
                 font=(FONT, 9)).pack(side="left", padx=(8, 0), pady=(14, 0))
        self.bar = ttk.Progressbar(body, style="Ram.Horizontal.TProgressbar",
                                   orient="horizontal", mode="determinate",
                                   maximum=100)
        self.bar.pack(fill="x", pady=(2, 10))
        stats = tk.Frame(body, bg=CARD)
        stats.pack(fill="x")
        stats.columnconfigure((0, 1, 2, 3), weight=1, uniform="s")
        self.st_total = self._stat_box(stats, 0, "TOPLAM", FG)
        self.st_used = self._stat_box(stats, 1, "KULLANILAN", BLUE)
        self.st_free = self._stat_box(stats, 2, "KULLANILABİLİR", GREEN)
        self.st_cache = self._stat_box(stats, 3, "ÖNBELLEK", CYAN)

        # Sistem özeti
        card, head, body = make_card(parent, "SİSTEM ÖZETİ")
        card.pack(fill="x", pady=(0, 8))
        grid = tk.Frame(body, bg=CARD)
        grid.pack(fill="x")
        grid.columnconfigure((0, 1, 2, 3), weight=1, uniform="t")
        self.t_swap = self._tile(grid, 0, "SWAP", with_bar=True)
        self.t_proc = self._tile(grid, 1, "İŞLEM")
        self.t_last = self._tile(grid, 2, "SON TEMİZLİK")
        self.t_sess = self._tile(grid, 3, "OTURUM")

        # Tahmini kazanç
        card, head, body = make_card(parent, "TAHMİNİ KAZANÇ")
        card.pack(fill="x", pady=(0, 8))
        tk.Label(head, text="●  CANLI HESAP", bg=CARD, fg=BLUE,
                 font=(FONT, 8, "bold")).pack(side="right")
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x")
        self.est_value = tk.Label(row, text="—", bg=CARD, fg=GREEN,
                                  font=(FONT, 20, "bold"))
        self.est_value.pack(side="left")
        self.est_sub = tk.Label(row, text="", bg=CARD, fg=FG_DIM, justify="right",
                                font=(FONT, 8))
        self.est_sub.pack(side="right")
        self.est_detail = tk.Label(body, text="", bg=CARD, fg="#b7b7c0", anchor="w",
                                   justify="left", wraplength=390, font=(FONT, 8))
        self.est_detail.pack(fill="x", pady=(4, 0))
        tk.Label(body, text="Kernel/process verilerinden hesaplanan aday havuzu üst sınırıdır; gerçek serbest kalan RAM daha düşük olabilir.",
                 bg=CARD, fg="#777783", anchor="w", wraplength=420,
                 justify="left", font=(FONT, 7)).pack(fill="x")

        # Ana buton
        self.button = tk.Button(
            parent, text="RAM TEMİZLE", command=self.on_clean, bg=GREEN,
            fg="#06220f", activebackground=GREEN_DARK, activeforeground="#06220f",
            disabledforeground="#0b3a1c", relief="flat", bd=0, cursor="hand2",
            font=(FONT, 14, "bold"), pady=11)
        self.button.pack(fill="x")
        self.button.bind("<Enter>", lambda e: self._btn_hover(True))
        self.button.bind("<Leave>", lambda e: self._btn_hover(False))
        self.busy_bar = ttk.Progressbar(parent, style="Busy.Horizontal.TProgressbar",
                                        orient="horizontal", mode="indeterminate")
        self.busy_bar.pack(fill="x", pady=(2, 0))
        self.notice = tk.Label(parent, text="", bg=BG, fg=GREEN, height=2,
                               wraplength=410, anchor="n",
                               font=(FONT, 11, "bold"))
        self.notice.pack(fill="x", pady=(6, 0))

    def _stat_box(self, parent, col, title, color):
        box = tk.Frame(parent, bg=CARD)
        box.grid(row=0, column=col, sticky="nsew", padx=2)
        tk.Label(box, text=title, bg=CARD, fg=FG_DIM,
                 font=(FONT, 8, "bold")).pack()
        gb = tk.Label(box, text="-- GB", bg=CARD, fg=color, font=(FONT, 12, "bold"))
        gb.pack(pady=(2, 0))
        pc = tk.Label(box, text="--%", bg=CARD, fg=FG_DIM, font=(FONT, 9))
        pc.pack()
        return gb, pc

    def _tile(self, parent, col, title, with_bar=False):
        f = tk.Frame(parent, bg=CARD2, highlightbackground=CARD_BORDER,
                     highlightthickness=1)
        f.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 4, 0))
        tk.Label(f, text=title, bg=CARD2, fg=FG_DIM,
                 font=(FONT, 7, "bold")).pack(anchor="w", padx=8, pady=(7, 0))
        val = tk.Label(f, text="--", bg=CARD2, fg=FG, font=(FONT, 10, "bold"))
        val.pack(anchor="w", padx=8)
        bar = None
        if with_bar:
            bar = ttk.Progressbar(f, style="Swap.Horizontal.TProgressbar",
                                  orient="horizontal", mode="determinate", maximum=100)
            bar.pack(fill="x", padx=8, pady=(2, 1))
        else:
            tk.Frame(f, bg=CARD2, height=9).pack()
        sub = tk.Label(f, text="", bg=CARD2, fg=FG_DIM, font=(FONT, 8))
        sub.pack(anchor="w", padx=8, pady=(0, 7))
        return val, sub, bar

    # ---- sağ sütun
    def _build_right(self, parent):
        # Açılır/kapanır ayarlar kartı
        self.settings_card = tk.Frame(parent, bg=CARD, highlightbackground=CARD_BORDER,
                                      highlightcolor=CARD_BORDER, highlightthickness=1)
        self.settings_card.pack(fill="x", pady=(0, 8))
        head = tk.Frame(self.settings_card, bg=CARD, cursor="hand2")
        head.pack(fill="x", padx=16, pady=(10, 8))
        title = tk.Label(head, text="⚙  TEMİZLİK SEÇENEKLERİ", bg=CARD, fg=FG_DIM,
                         font=(FONT, 8, "bold"), cursor="hand2")
        title.pack(side="left")
        self.arrow = tk.Label(head, text="▾", bg=CARD, fg=BLUE,
                              font=(FONT, 11, "bold"), cursor="hand2")
        self.arrow.pack(side="right")
        for w in (head, title, self.arrow):
            w.bind("<Button-1>", lambda e: self._toggle_settings())
        self.settings_body = tk.Frame(self.settings_card, bg=CARD)
        self._build_settings_body(self.settings_body)
        self._set_settings_open(self.settings_open, save=False)

        # İşlem günlüğü
        card, head, body = make_card(parent, "İŞLEM GÜNLÜĞÜ")
        card.pack(fill="both", expand=True)
        GhostButton(head, "TEMİZLE", self._clear_log).pack(side="right")
        self.log_text = tk.Text(body, height=6, width=40, wrap="word", bg="#0d0d0f",
                                fg="#b7b7c0", insertbackground="#0d0d0f", bd=0,
                                highlightthickness=0, padx=8, pady=6,
                                font=(MONO, 8), state="disabled", cursor="arrow")
        sb = ttk.Scrollbar(body, orient="vertical", style="Dark.Vertical.TScrollbar",
                           command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        for tag, color in (("ts", "#5b5b66"), ("info", "#b7b7c0"), ("ok", GREEN),
                           ("warn", AMBER), ("err", RED)):
            self.log_text.tag_configure(tag, foreground=color)

    def _build_settings_body(self, parent):
        language_row = tk.Frame(parent, bg=CARD)
        language_row.pack(fill="x", pady=(0, 8))
        tk.Label(language_row, text="Uygulama dili", bg=CARD, fg=FG,
                 font=(FONT, 9, "bold")).pack(side="left")
        self.language_var = tk.StringVar(value=LANGUAGE_NAMES[self.language])
        self.language_combo = ttk.Combobox(
            language_row, textvariable=self.language_var,
            values=tuple(LANGUAGE_NAMES[code] for code in LANGUAGE_ORDER),
            state="readonly", width=14)
        self.language_combo.pack(side="right")
        self.language_combo.bind("<<ComboboxSelected>>", self._change_language)
        tk.Frame(parent, bg=CARD_BORDER, height=1).pack(fill="x", pady=(0, 8))

        def row(text, desc, var):
            CheckRow(parent, text, desc, var).pack(fill="x", pady=3)

        if IS_LINUX:
            row("PageCache (Sayfa Önbelleği)",
                "Dosya içeriği önbelleği  •  drop_caches=1", self.v_pagecache)
            row("Dentries & Inodes",
                "Dizin/dosya yapısı önbelleği  •  drop_caches=2", self.v_dentries)
            row("Swap Sıfırlama",
                "Swap'i RAM'e geri alıp yeniden açar  •  yavaş olabilir", self.v_swap)
            row("Önce sync çalıştır",
                "Yazılmamış verileri diske yazar (önerilir)", self.v_sync)
        else:
            row("Arka Plan Working Set",
                "Süreçlerin kullanılmayan çalışma belleğini boşaltır", self.v_ws)
            row("Sistem Önbelleği",
                "Dosya sistemi önbelleğini küçültür  •  Yönetici gerekir",
                self.v_syscache)

        tk.Frame(parent, bg=CARD_BORDER, height=1).pack(fill="x", pady=(8, 8))
        tk.Label(parent, text="OTOMATİK ZAMANLAYICI", bg=CARD, fg=FG_DIM,
                 font=(FONT, 8, "bold")).pack(anchor="w", pady=(0, 4))
        row("Otomatik temizleme",
            "RAM kullanımı eşiği aşınca kendiliğinden temizler", self.v_auto)
        self._slider_row(parent, "Kullanım eşiği", self.v_thr, 50, 95, 5,
                         lambda v: f"%{v}")
        self._slider_row(parent, "Bekleme süresi", self.v_cd, 1, 60, 1,
                         lambda v: f"{v} dk")

    def _change_language(self, event=None):
        global ACTIVE_LANGUAGE
        selected_name = self.language_var.get()
        new_language = next(
            (code for code, name in LANGUAGE_NAMES.items() if name == selected_name),
            self.language)
        if new_language == self.language:
            return
        try:
            selected_tab = self.notebook.index(self.notebook.select())
        except Exception:
            selected_tab = 0

        self.language = new_language
        ACTIVE_LANGUAGE = new_language
        self._save_now()

        # Remove callbacks attached to labels that are about to be destroyed.
        for variable, trace_id in self._slider_trace_ids:
            try:
                variable.trace_remove("write", trace_id)
            except Exception:
                pass
        self._slider_trace_ids.clear()

        # Rebuild only the widgets; monitoring and background workers keep running.
        for child in self.root.winfo_children():
            child.destroy()
        self._build_ui()
        tabs = self.notebook.tabs()
        if tabs:
            self.notebook.select(tabs[min(selected_tab, len(tabs) - 1)])
        self._fit_window()
        if self._last_snap is not None:
            self._render_stats(self._last_snap)
            self._update_estimate()
        if self.busy:
            self.button.configure(text="TEMİZLENİYOR...", state="disabled", bg=GREEN_DARK)
            self.busy_bar.start(12)
        if self.storage_busy:
            self.storage_scan_button.configure(state="disabled")
            self.storage_clean_button.configure(state="disabled")
            self.storage_status.configure(text="Önizlemede listelenen dosyalar tekrar doğrulanıyor ve temizleniyor…",
                                          fg=AMBER)

    def _slider_row(self, parent, title, var, lo, hi, step, fmt):
        f = tk.Frame(parent, bg=CARD)
        f.pack(fill="x", pady=(4, 0))
        top = tk.Frame(f, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text=title, bg=CARD, fg=FG, font=(FONT, 9)).pack(side="left")
        val = tk.Label(top, text=fmt(var.get()), bg=CARD, fg=BLUE,
                       font=(FONT, 9, "bold"))
        val.pack(side="right")
        FlatSlider(f, var, lo, hi, step).pack(fill="x")
        trace_id = var.trace_add("write", lambda *a: val.configure(text=fmt(var.get())))
        self._slider_trace_ids.append((var, trace_id))

    def _toggle_settings(self):
        self._set_settings_open(not self.settings_open)

    def _set_settings_open(self, is_open, save=True):
        self.settings_open = is_open
        if is_open:
            self.settings_body.pack(fill="x", padx=16, pady=(0, 12))
            self.arrow.configure(text="▾")
        else:
            self.settings_body.pack_forget()
            self.arrow.configure(text="▸")
        if save:
            self._schedule_save()

    def _fit_window(self):
        """Sekmeli arayüzü ekrana sığdır; pencere yeniden boyutlandırılabilir."""
        root = self.root
        root.update_idletasks()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        req_w, req_h = root.winfo_reqwidth(), root.winfo_reqheight()
        w = min(max(req_w, 980), max(640, sw - 40))
        h = min(max(req_h, 720), max(520, sh - 80))
        x = max((sw - w) // 2, 10)
        y = max((sh - h) // 3, 10)
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.minsize(min(900, max(640, sw - 40)), min(620, max(520, sh - 80)))
        root.resizable(True, True)

    # ---------------------------------------------------------- günlük/bildirim
    def log(self, level, msg):
        msg = _tr(msg)
        icon = {"ok": "✓", "warn": "!", "err": "✗"}.get(level, "•")
        t = self.log_text
        t.configure(state="normal")
        t.insert("end", datetime.now().strftime("%H:%M:%S") + "  ", "ts")
        t.insert("end", f"{icon} {msg}\n", level)
        lines = int(t.index("end-1c").split(".")[0])
        if lines > 400:
            t.delete("1.0", f"{lines - 400}.0")
        t.configure(state="disabled")
        t.see("end")

    def _clear_log(self):
        t = self.log_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.configure(state="disabled")

    def _log_startup(self):
        self.log("info", f"{APP_SHORT} v{APP_VERSION} başlatıldı")
        try:
            s = take_snapshot()
            self.log("info", f"{os_pretty()}  •  toplam RAM {fmt_size(s.total)}")
        except Exception as exc:
            self.log("err", f"Bellek bilgisi okunamadı: {exc}")
        if has_privileges():
            self.log("ok", "Yetki durumu: tam temizlik mümkün")
        elif IS_LINUX:
            self.log("warn", "Root yetkisi yok: Tam temizlik için sudo ile çalıştırın")
        else:
            self.log("warn", "Yönetici yetkisi yok: temizlik sınırlı olabilir")

    def _show_notice(self, text, color, seconds=10):
        text = _tr(text)
        if self._notice_job is not None:
            self.root.after_cancel(self._notice_job)
        self.notice.configure(text=text, fg=color)
        self._notice_job = self.root.after(
            seconds * 1000, lambda: self.notice.configure(text=""))

    def _btn_hover(self, inside):
        if not self.busy:
            self.button.configure(bg=GREEN_DARK if inside else GREEN)

    # ------------------------------------------------------------ ayar takibi
    def get_options(self) -> CleanOptions:
        return CleanOptions(
            pagecache=bool(self.v_pagecache.get()),
            dentries=bool(self.v_dentries.get()),
            swap_reset=bool(self.v_swap.get()),
            sync_first=bool(self.v_sync.get()),
            working_set=bool(self.v_ws.get()),
            system_cache=bool(self.v_syscache.get()),
        )

    def _wire_traces(self):
        for var in (self.v_pagecache, self.v_dentries, self.v_swap, self.v_sync,
                    self.v_ws, self.v_syscache, self.v_auto, self.v_thr, self.v_cd):
            var.trace_add("write", self._on_setting_changed)

    def _on_setting_changed(self, *_):
        self._update_estimate()
        self._schedule_save()

    def _schedule_save(self):
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(600, self._save_now)

    def _save_now(self):
        self._save_job = None
        save_settings({
            "version": 1,
            "opts": asdict(self.get_options()),
            "auto_enabled": bool(self.v_auto.get()),
            "auto_threshold": int(self.v_thr.get()),
            "auto_cooldown": int(self.v_cd.get()),
            "settings_open": self.settings_open,
            "last_clean_ts": self.last_clean_ts,
            "language": self.language,
        })

    # ------------------------------------------------------- canlı güncelleme
    def _tick(self):
        try:
            snap = take_snapshot()
            self._last_snap = snap
            self._last_tick_err = None
            self._render_stats(snap)
            self._update_estimate()
            self._check_auto(snap)
        except Exception as exc:
            msg = str(exc)
            if msg != self._last_tick_err:
                self._last_tick_err = msg
                self.log("err", f"Bellek okunamadı: {msg}")
        finally:
            self.root.after(1000, self._tick)

    def _render_stats(self, s: MemSnapshot):
        total = s.total or 1
        used_pct = s.used / total * 100
        self.pct_label.configure(text=f"{used_pct:.0f}%")
        self.bar["value"] = used_pct
        color = BLUE if used_pct < 65 else (AMBER if used_pct < 85 else RED)
        self.style.configure("Ram.Horizontal.TProgressbar", background=color,
                             lightcolor=color, darkcolor=color)

        def put(box, value):
            box[0].configure(text=f"{value / GB:.2f} GB")
            box[1].configure(text=f"%{value / total * 100:.1f}")

        put(self.st_total, s.total)
        self.st_total[1].configure(text="100%")
        put(self.st_used, s.used)
        put(self.st_free, s.free)
        put(self.st_cache, s.cached)

        # Sistem özeti
        val, sub, bar = self.t_swap
        if s.swap_total > 0:
            sp = s.swap_used / s.swap_total * 100
            val.configure(text=f"{s.swap_used / GB:.1f}/{s.swap_total / GB:.1f} GB")
            sub.configure(text=f"%{sp:.0f} dolu")
            bar["value"] = sp
        else:
            val.configure(text="Yok")
            sub.configure(text="swap etkin değil")
            bar["value"] = 0

        val, sub, _ = self.t_proc
        val.configure(text=str(count_processes()))
        sub.configure(text="çalışan süreç")

        val, sub, _ = self.t_last
        if self.last_clean_ts:
            dt = datetime.fromtimestamp(self.last_clean_ts)
            same_day = dt.date() == datetime.now().date()
            val.configure(text=dt.strftime("%H:%M:%S" if same_day else "%d.%m %H:%M"))
            sub.configure(text=fmt_ago(self.last_clean_ts))
        else:
            val.configure(text="Henüz yok")
            sub.configure(text="-")

        val, sub, _ = self.t_sess
        val.configure(text=fmt_size(self.session_freed))
        sub.configure(text=f"{self.session_cleans} temizlik")

    def _update_estimate(self):
        snap = self._last_snap
        if snap is None:
            return
        opts = self.get_options()
        if not opts.any_selected():
            self.est_value.configure(text="—", fg=FG_DIM)
            self.est_sub.configure(text="seçenek seçilmedi")
            self.est_detail.configure(
                text="Sağdaki panelden en az bir temizlik seçeneği işaretleyin.")
            return
        total, items = estimate_gain(opts, snap, self.ws_bytes)
        pct = total / (snap.total or 1) * 100
        self.est_value.configure(text=f"≈ {fmt_size(total)}",
                                 fg=GREEN if total >= 0 else AMBER)
        self.est_sub.configure(
            text=f"{total / MB:.0f} MB  •  {total / GB:.2f} GB\n"
                 f"toplam RAM'in %{pct:.1f}'i · üst sınır")
        lines = []
        for label, v in items:
            lines.append(f"•  {label}: " + (f"−{fmt_size(-v)}" if v < 0
                                            else f"≈ {fmt_size(v)}"))
        self.est_detail.configure(text="\n".join(lines))

    def _ws_loop(self):
        """Windows: süreçlerin özel (USS) resident belleğini periyodik ölçer."""
        while not self._stop:
            total_uss = 0
            try:
                for proc in psutil.process_iter():
                    try:
                        # psutil 8.x, memory_full_info() yerine memory_footprint()
                        # API'sini önerir. Eski sürümler için geriye dönük uyumluluk.
                        footprint = getattr(proc, "memory_footprint", None)
                        mem = footprint() if callable(footprint) else proc.memory_full_info()
                        total_uss += int(getattr(mem, "uss", 0) or 0)
                    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                        continue
                    except Exception:
                        continue
                self.ws_bytes = total_uss
            except Exception:
                self.ws_bytes = 0
            for _ in range(6):
                if self._stop:
                    return
                time.sleep(1)

    # ------------------------------------------------------- otomatik temizlik
    def _check_auto(self, snap: MemSnapshot):
        if not self.v_auto.get() or self.busy:
            return
        used_pct = snap.used / (snap.total or 1) * 100
        thr = int(self.v_thr.get())
        if used_pct < thr:
            return
        if time.time() - self.last_auto_ts < int(self.v_cd.get()) * 60:
            return
        self.last_auto_ts = time.time()
        self.log("info", f"Otomatik zamanlayıcı: kullanım %{used_pct:.0f} ≥ eşik %{thr}")
        self.on_clean(auto=True)

    # ------------------------------------------------------------- temizleme
    def on_clean(self, auto=False):
        if self.busy:
            return
        opts = self.get_options()
        if not opts.any_selected():
            if not auto:
                self._show_notice("En az bir temizlik seçeneği seçin.", AMBER)
                self.log("warn", "Temizlik için seçenek seçilmedi")
            return
        if IS_LINUX and not is_root_linux():
            if not auto:
                self._show_notice("Tam temizlik için sudo ile çalıştırın", AMBER)
                self.log("warn", "Root yetkisi yok: Tam temizlik için sudo ile çalıştırın")
            elif not self._warned_auto:
                self._warned_auto = True
                self.log("warn", "Otomatik temizleme için root yetkisi gerekli")
            return

        self.busy = True
        self._swap_running = bool(IS_LINUX and opts.swap_reset)
        self.button.configure(text="TEMİZLENİYOR...", state="disabled", bg=GREEN_DARK)
        self.busy_bar.start(12)
        self.notice.configure(text="Temizlik sürüyor, lütfen bekleyin...", fg=FG_DIM)
        threading.Thread(target=self._worker, args=(opts, auto), daemon=True).start()

    def _worker(self, opts, auto):
        """Arka plan iş parçacığı: arayüze dokunmaz, her şeyi kuyruğa yazar."""
        def log(level, msg):
            self.q.put(("log", level, msg))
        try:
            before = take_snapshot()
            log("info", f"Temizlik başlatıldı ({'otomatik' if auto else 'manuel'})  •  "
                        f"önce: kullanılan {fmt_size(before.used)}, "
                        f"kullanılabilir {fmt_size(before.free)}")
            if IS_LINUX:
                ok, err = clean_linux(opts, log)
            else:
                ok, err = clean_windows(opts, log)
            time.sleep(1.5)  # sayaçların güncellenmesi için kısa bekleme
            after = take_snapshot()
            gained = after.free - before.free
            log("info", f"Sonra: kullanılan {fmt_size(after.used)}, "
                        f"kullanılabilir {fmt_size(after.free)}  (fark {fmt_size(gained)})")
            self.q.put(("done", ok, err, gained, auto))
        except Exception as exc:
            log("err", f"Beklenmeyen hata: {exc}")
            self.q.put(("done", False, str(exc), 0, auto))

    def _poll_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "log":
                    self.log(item[1], item[2])
                elif item[0] == "done":
                    self._finish(*item[1:])
                elif item[0] == "storage_scan_done":
                    self._finish_storage_scan(*item[1:])
                elif item[0] == "storage_clean_done":
                    self._finish_storage_clean(*item[1:])
                elif item[0] in ("storage_scan_error", "storage_clean_error"):
                    self._finish_storage_error(item[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _finish(self, ok, err, gained, auto):
        self.busy = False
        self._swap_running = False
        self.busy_bar.stop()
        self.button.configure(text="RAM TEMİZLE", state="normal", bg=GREEN)
        if not ok:
            self._show_notice(f"Hata: {err}" if err else "Temizlik tamamlanamadı", RED)
            return
        gained_mb = max(gained, 0) / MB
        self.last_clean_ts = time.time()
        self.session_cleans += 1
        self.session_freed += max(gained, 0)
        if gained_mb >= 1:
            self._show_notice(f"Kullanılabilir RAM ölçümünde +{gained_mb:.0f} MB fark", GREEN)
            self.log("ok", f"Kullanılabilir RAM ölçüm farkı: +{gained_mb:.0f} MB")
        else:
            self._show_notice("Temizlik tamamlandı (belirgin kullanılabilir RAM artışı ölçülmedi).",
                              GREEN)
            self.log("ok", "Temizlik tamamlandı; belirgin kullanılabilir RAM artışı ölçülmedi")
        self._schedule_save()
        try:
            snap = take_snapshot()
            self._last_snap = snap
            self._render_stats(snap)
            self._update_estimate()
        except Exception:
            pass

    def _on_close(self):
        if self.busy and self._swap_running:
            self._show_notice("Swap sıfırlama sürüyor, bitmesini bekleyin.", AMBER)
            return
        if self.storage_busy:
            self._show_notice("Depolama taraması/temizliği sürüyor; işlem bitince kapatın.", AMBER)
            return
        self._stop = True
        self._save_now()
        self.root.destroy()


# =========================================================================== #
#  GİRİŞ NOKTASI
# =========================================================================== #
def selftest() -> int:
    """Arayüzsüz motor testi (--selftest)."""
    global ACTIVE_LANGUAGE
    previous_language = ACTIVE_LANGUAGE
    try:
        for language in LANGUAGE_ORDER:
            ACTIVE_LANGUAGE = language
            sample = _tr("RAM TEMİZLE")
            if language != "tr" and sample == "RAM TEMİZLE":
                raise RuntimeError(f"Translation missing for {language}")
    finally:
        ACTIVE_LANGUAGE = previous_language
    print(f"Dil testleri: {len(LANGUAGE_ORDER)}/{len(LANGUAGE_ORDER)} başarılı ({', '.join(LANGUAGE_NAMES.values())})")
    print(f"{APP_NAME} v{APP_VERSION} selftest  |  {os_pretty()}  |  python {platform.python_version()}")
    s = take_snapshot()
    print(f"RAM toplam {fmt_size(s.total)}, kullanılan {fmt_size(s.used)}, "
          f"kullanılabilir {fmt_size(s.free)}, önbellek {fmt_size(s.cached)}, "
          f"swap {fmt_size(s.swap_used)}/{fmt_size(s.swap_total)}")
    print(f"İşlem sayısı: {count_processes()}")
    total, items = estimate_gain(CleanOptions(swap_reset=True), s, 0)
    print(f"Tahmini kazanç: {fmt_size(total)}")
    for label, v in items:
        print(f"   {label}: {fmt_size(v)}")
    png = generate_logo_png(32)
    sig_ok = png[:8] == b"\x89PNG\r\n\x1a\n"
    print(f"Logo PNG: {len(png)} bayt, imza {'OK' if sig_ok else 'HATA'}")
    print(f"Yetki: {'var' if has_privileges() else 'yok'}  |  ayar dosyası: {settings_path()}")
    print(f"tkinter: {'var' if TK_OK else 'YOK (sudo apt install -y python3-tk)'}  |  "
          f"psutil: {'var' if psutil else 'yok'}")
    try:
        temp_items, temp_errors, temp_limited = scan_temp_files()
        temp_bytes = sum(item.size for item in temp_items)
        print(f"Geçici dosya önizlemesi: {len(temp_items)} dosya, {fmt_size(temp_bytes)} "
              f"(hata={temp_errors}, limit={temp_limited}; silme yapılmadı)")
    except Exception as exc:
        print(f"Geçici dosya taraması kullanılamıyor: {exc}")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if not TK_OK:
        print("tkinter bulunamadı. Lubuntu/Ubuntu için kurulum:")
        print("    sudo apt install -y python3-tk")
        return 1
    if not (IS_LINUX or IS_WINDOWS):
        print(f"Desteklenmeyen işletim sistemi: {OS_NAME}")
        return 2
    if IS_WINDOWS:
        try:  # Windows'ta bulanık yazıyı önle
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Pencere açılamadı (ekran bulunamadı?): {exc}")
        print("sudo ile açıyorsanız deneyin:  sudo -E python3 cramc.py")
        return 2
    CramcApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())