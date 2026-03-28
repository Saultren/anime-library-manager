import os
import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass

import libtorrent as lt

@dataclass
class TorrentStatus:
    """Текущий статус загрузки"""
    info_hash: str
    name: str
    state: str
    progress: float
    download_speed: int
    uploaded: int
    total_downloaded: int
    total_size: int
    num_peers: int
    num_seeds: int
    is_finished: bool
    save_path: str
    error: Optional[str] = None

class TorrentManager:
    """Управление торрент-загрузками через libtorrent (потокобезопасная версия)"""
    
    def __init__(self, save_path: Path, loop: asyncio.AbstractEventLoop):
        self.save_path = Path(save_path).expanduser().resolve()
        self.save_path.mkdir(parents=True, exist_ok=True)
        self.loop = loop
        
        # Все операции с session будут выполняться в этом выделенном потоке
        self._session: Optional[lt.session] = None
        self._active_downloads: Dict[str, lt.torrent_handle] = {}
        
        # Инициализируем сессию в отдельном потоке
        self._init_session()
        
        logging.info(f"TorrentManager инициализирован: {self.save_path}")

    def _init_session(self):
        """Инициализация сессии в текущем потоке"""
        self._session = lt.session({'listen_interfaces': '0.0.0.0:6881'})
        settings = {
            'user_agent': 'AnimeLibrary/1.0',
            'announce_to_all_trackers': True,
            'announce_to_all_tiers': True,
            'connections_limit': 100,
            'upload_rate_limit': 0,
            'download_rate_limit': 0,
            'stop_tracker_timeout': 5,
        }
        self._session.apply_settings(settings)

    async def add_torrent(self, torrent_file: Path, release_name: str) -> str:
        """Добавить .torrent файл в сессию (асинхронно)"""
        return await asyncio.to_thread(self._add_torrent_sync, torrent_file, release_name)

    def _add_torrent_sync(self, torrent_file: Path, release_name: str) -> str:
        """Синхронная версия добавления торрента (вызывается в отдельном потоке)"""
        try:
            # Читаем торрент
            with open(torrent_file, 'rb') as f:
                torrent_data = lt.bdecode(f.read())
            
            info = lt.torrent_info(torrent_data)
            
            # FIX: Корректное получение info_hash для libtorrent 2.x
            try:
                info_hash = info.info_hash().to_string().hex()
            except AttributeError:
                # Для старых версий libtorrent
                info_hash = str(info.info_hash())
            
            # Проверяем, не качаем ли уже
            if info_hash in self._active_downloads:
                logging.info(f"Торрент уже активен: {info_hash}")
                return info_hash
            
            # Создаем подпапку для релиза, чтобы файлы не сваливались в кучу
            release_save_path = self.save_path / release_name
            release_save_path.mkdir(parents=True, exist_ok=True)
            
            # Параметры загрузки
            params = {
                'ti': info,
                'save_path': str(release_save_path),
                'storage_mode': lt.storage_mode_t.storage_mode_sparse,
            }
            
            handle = self._session.add_torrent(params)
            handle.set_sequential_download(True)  # Для видео
            
            self._active_downloads[info_hash] = handle
            logging.info(f"Добавлен торрент: {info_hash} → {release_save_path}")
            
            return info_hash
            
        except Exception as e:
            logging.error(f"Ошибка добавления торрента: {e}")
            raise

    async def get_status(self, info_hash: str) -> Optional[TorrentStatus]:
        """Получить текущий статус загрузки (асинхронно)"""
        return await asyncio.to_thread(self._get_status_sync, info_hash)

    def _get_status_sync(self, info_hash: str) -> Optional[TorrentStatus]:
        """Синхронная версия получения статуса"""
        if info_hash not in self._active_downloads:
            return None
            
        handle = self._active_downloads[info_hash]
        status = handle.status()
        
        # Определяем состояние
        state_map = {
            lt.torrent_status.checking_resume_data: "checking",
            lt.torrent_status.checking_files: "checking",
            lt.torrent_status.downloading_metadata: "downloading",
            lt.torrent_status.downloading: "downloading",
            lt.torrent_status.finished: "finished",
            lt.torrent_status.seeding: "seeding",
        }
        state = state_map.get(status.state, "unknown")
        
        return TorrentStatus(
            info_hash=info_hash,
            name=status.name if handle.has_metadata() else "Загрузка метаданных...",
            state=state,
            progress=status.progress,
            download_speed=status.download_rate,
            uploaded=status.total_upload,
            total_downloaded=status.total_done,
            total_size=status.total_wanted,
            num_peers=status.num_peers,
            num_seeds=status.num_seeds,
            is_finished=status.is_finished,
            save_path=handle.save_path(),
            error=status.error if status.error else None
        )

    async def pause_download(self, info_hash: str):
        """Пауза загрузки (асинхронно)"""
        await asyncio.to_thread(self._pause_download_sync, info_hash)

    def _pause_download_sync(self, info_hash: str):
        """Синхронная версия паузы"""
        if info_hash in self._active_downloads:
            self._active_downloads[info_hash].pause()
            logging.info(f"Пауза: {info_hash}")

    async def resume_download(self, info_hash: str):
        """Возобновить загрузку (асинхронно)"""
        await asyncio.to_thread(self._resume_download_sync, info_hash)

    def _resume_download_sync(self, info_hash: str):
        """Синхронная версия возобновления"""
        if info_hash in self._active_downloads:
            self._active_downloads[info_hash].resume()
            logging.info(f"Возобновлено: {info_hash}")

    async def remove_download(self, info_hash: str, delete_files: bool = False):
        """Удалить загрузку из сессии (асинхронно)"""
        await asyncio.to_thread(self._remove_download_sync, info_hash, delete_files)

    def _remove_download_sync(self, info_hash: str, delete_files: bool = False):
        """Синхронная версия удаления"""
        if info_hash in self._active_downloads:
            handle = self._active_downloads[info_hash]
            
            if delete_files:
                import shutil
                save_path = Path(handle.save_path())
                if save_path.exists():
                    shutil.rmtree(save_path)
                    logging.info(f"Удалены файлы: {save_path}")
            
            self._session.remove_torrent(handle)
            del self._active_downloads[info_hash]
            logging.info(f"Удален торрент: {info_hash}")

    async def get_all_statuses(self) -> List[TorrentStatus]:
        """Получить статус всех активных загрузок (асинхронно)"""
        return await asyncio.to_thread(self._get_all_statuses_sync)

    def _get_all_statuses_sync(self) -> List[TorrentStatus]:
        """Синхронная версия получения всех статусов"""
        statuses = []
        for ih in self._active_downloads:
            status = self._get_status_sync(ih)
            if status:
                statuses.append(status)
        return statuses

    async def shutdown(self):
        """Корректное завершение (асинхронно)"""
        await asyncio.to_thread(self._shutdown_sync)

    def _shutdown_sync(self):
        """Синхронная версия завершения"""
        logging.info("Остановка TorrentManager...")
        for handle in self._active_downloads.values():
            handle.pause()
        if self._session:
            self._session.pause()
        logging.info("TorrentManager остановлен")

    @property
    def active_downloads(self) -> Dict[str, lt.torrent_handle]:
        """Возвращает словарь активных загрузок (только для чтения, без блокировок)"""
        return self._active_downloads.copy()
