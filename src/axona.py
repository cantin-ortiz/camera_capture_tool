"""
Manipulate Axona RAW Files.

This module contains classes and functions to manipulate data from Axona
Electrophysiology recording systems. Currently the module only handles .bin
files recorded using the system in RAW mode.
"""
import logging
from mmap import mmap, ACCESS_READ
from typing import BinaryIO, Dict, Iterable, List, Tuple, Union
from datetime import datetime
from pathlib import Path
import numpy as np
from scipy import interpolate, signal
logger = logging.getLogger(__name__)


class RawFile(object):
    """Read data from an Axona .bin file."""

    _tracker_remapping: List = [1, 0, 3, 2, 5, 4, 7, 6]

    def __init__(self, filename: Union[str, Path]) -> None:
        """Create RawFile object.

        Args:
            filename (Union[str, Path]): RAW recording file name

        Raises:
            ValueError: The file has a fractional number of packets and is
                        likely corrupt
        """
        self._filename: Path = Path(filename)
        self._fd: Union[BinaryIO, None] = None
        self._mm: Union[mmap, None] = None
        self._pkg_size: int = 432
        # Makes the generator read a little more than 4MB each time
        self._blk_size: int = 10000

        nbytes = self._filename.stat().st_size

        if nbytes % self._pkg_size:
            raise ValueError(
                "File size is not an integer multiple of packet size")

        self._n_pkgs = nbytes // self._pkg_size

    def __len__(self) -> int:
        """Return length of recording.

        Returns:
            int: Number of packets in recording
        """
        return self._n_pkgs

    def __iter__(self):
        """Return iterator over raw packets."""
        for i in range(len(self)):
            start = i*self._pkg_size
            stop = (i+1)*self._pkg_size
            yield self._mm[start:stop]

    def __getitem__(self, index: int):
        """Return data for packet at index."""
        start = index * self._pkg_size
        stop = (index + 1) * self._pkg_size
        return self._mm[start:stop]

    def __enter__(self):
        """Open recording in context manager."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Close recording in context manager."""
        self.close()

    def open(self) -> None:
        """Open recording for reading."""
        self._fd = self._filename.open('rb')
        self._mm = mmap(self._fd.fileno(), 0, access=ACCESS_READ)

    def close(self):
        """Close the recording."""
        self._mm.close()
        self._fd.close()
        self._mm = None
        self._fd = None

    @staticmethod
    def read_packet(data_pkg: bytearray) -> Tuple[
        str, int, np.ndarray, np.ndarray,
        int, np.ndarray, np.ndarray, np.ndarray,
        np.ndarray, str
    ]:
        """Read an Axona packet.

        Args:
            data_pkg (bytearray): Raw binary data from an Axona packet

        Returns:
            pkg_id (str): Packet ID
            pkg_num (int): Packet number
            digital_in (ndarray): Digital input status
            sync_in (ndarray): Digital sync status
            frame_ctr (int): Frame number from tracker
            pos_tracking (ndarray): Position tracker data
            data (ndarray): Three samples of electrophysiological data
            digital_out (ndarray): Digital output status
            stim_status (ndarray): Digital stimulator status
            keys_pressed (str): Key(s) pressed
        """
        pkg_id = data_pkg[:4].decode('ascii')
        pkg_num = np.frombuffer(data_pkg[4:8], dtype=np.uint32).view(np.dtype(np.uint32).newbyteorder('<'))
        digital_in = np.unpackbits(np.frombuffer(
            data_pkg[8:10], dtype=np.uint8)[::-1], bitorder='little').ravel()
        sync_in = np.unpackbits(np.frombuffer(
            data_pkg[10:12], dtype=np.uint8)[::-1], bitorder='little').ravel()
        frame_ctr = np.frombuffer(data_pkg[12:16], dtype=np.uint32).view(np.dtype(np.uint32).newbyteorder('<'))
        pos_tracking = np.frombuffer(data_pkg[16:32], dtype=np.uint16).view(np.dtype(np.uint16).newbyteorder('<'))
        pos_tracking = pos_tracking[RawFile._tracker_remapping]
        data = np.frombuffer(data_pkg[32:-16], dtype=np.int16).view(np.dtype(np.int16).newbyteorder('<')).reshape(-1, 64)
        digital_out = np.unpackbits(np.frombuffer(
            data_pkg[-16:-14], dtype=np.uint8)[::-1], bitorder='little')
        digital_out = digital_out.ravel()
        stim_status = np.unpackbits(np.frombuffer(
            data_pkg[-14:-12], dtype=np.uint8)[::-1], bitorder='little')
        stim_status = stim_status.ravel()
        keys_pressed = data_pkg[-2:].decode('ascii')

        return (pkg_id, pkg_num, digital_in, sync_in, frame_ctr, pos_tracking,
                data, digital_out, stim_status, keys_pressed)


class Recording(object):
    """Read and manipulate an Axona raw Recording."""

    _axona_channel_remap = (32, 33, 34, 35, 36, 37, 38, 39,
                            0,   1,  2,  3,  4,  5,  6,  7,
                            40, 41, 42, 43, 44, 45, 46, 47,
                            8,   9, 10, 11, 12, 13, 14, 15,
                            48, 49, 50, 51, 52, 53, 54, 55,
                            16, 17, 18, 19, 20, 21, 22, 23,
                            56, 57, 58, 59, 60, 61, 62, 63,
                            24, 25, 26, 27, 28, 29, 30, 31)
    _axona_inverse_channel_remap = np.arange(64)[_axona_channel_remap, ]
    _128ch_pk_slice = (slice(None, 64), slice(64, None))
    _traces_pk_slice = (slice(None), _axona_channel_remap)

    def __init__(self, recording_name: str,
                 keep_channels: Union[Iterable, int] = None,
                 traces_map_file: Union[Path, str] = None,
                 root: Union[Path, str] = Path('.')) -> None:
        """Create Recording object.

        Args:
            recording_name (str): Base name of the recording
            keep_channels (Union[Iterable, None], optional): List of channels
                from the recording to keep. Defaults to None (keep all).
            traces_map_file (Union[Path, None], optional): Name of the file
                where traces are written on-disk. Defaults to None.
            root (Union[Path, str], optional): Root directory where recording
                is located. Defaults to Path('.').

        Raises:
            FileNotFoundError: Recording data and/or settings are missing
        """
        self._raw_data_path = Path(root)/Path(recording_name + ".bin")
        self._set_file_path = Path(root)/Path(recording_name + ".set")
        if not self._set_file_path.is_file():
            raise FileNotFoundError(
                f"Can't open settings file {str(self._set_file_path)}")
        self._settings = read_set_file(self._set_file_path)
        # Create temporary directory for traces
        self._packet_ids: np.ndarray = None
        self._packet_num: np.ndarray = None
        self._digital_in: np.ndarray = None
        self._digital_out: np.ndarray = None
        self._sync_in: np.ndarray = None
        self._frame_counter: np.ndarray = None
        self._position: np.ndarray = None
        self._stimulator_status: np.ndarray = None
        self._keys_pressed: np.ndarray = None
        self._mode_128ch = bool(int(self._settings['mode128channels']))
        self._traces: np.ndarray = None
        self._traces_map_file = traces_map_file

        try:
            self.valid_channels: np.ndarray = keep_channels
        except ValueError as v:
            logger.exception(v)

    @property
    def valid_channels(self) -> np.ndarray:
        """Get valid channels."""
        return self._valid_channels

    @valid_channels.setter
    def valid_channels(self,
                       keep_channels: Union[Iterable, np.ndarray]) -> None:
        """Set valid channels."""
        # check if a list of valid channels to keep is supplied and make
        # a mask to filter out unwanted channels
        if isinstance(keep_channels, int):
            if keep_channels > 128:
                raise ValueError("Invalid channel selection")
            elif keep_channels > 64 and not self._mode_128ch:
                raise ValueError("Invalid channel selection")
            elif self._mode_128ch:
                self._valid_channels = np.zeros(128, dtype=bool)
                self._valid_channels[:keep_channels] = True
            else:
                self._valid_channels = np.zeros(64, dtype=bool)
                self._valid_channels[:keep_channels] = True
        elif keep_channels is not None:
            keep_channels = np.asarray(keep_channels)
            if np.any(keep_channels > 127):
                raise ValueError("Invalid channel selection")
            elif np.any(keep_channels > 63) and not self._mode_128ch:
                raise ValueError("Invalid channel selection")

            if self._mode_128ch:
                self._valid_channels = np.zeros(128, dtype=bool)
                self._valid_channels[keep_channels] = True
            else:
                self._valid_channels = np.zeros(64, dtype=bool)
                self._valid_channels[keep_channels] = True
        else:
            if self._mode_128ch:
                self._valid_channels = np.ones(128, dtype=bool)
            else:
                self._valid_channels = np.ones(64, dtype=bool)

    def write_axona(self, out_path: str) -> None:
        """Write recording data to disk in Axona file format."""
        logger.info(f"Writing file {out_path} in Axona format")
        if self._traces is None:
            self._data_load_helper(load_traces=True)
        with open(out_path+'.bin', 'wb') as data_out:
            for i in range(self._packet_num.size):
                trace_idx = (
                    slice(i*3, (i+1)*3),
                    self._axona_inverse_channel_remap
                )
                pkg = b''
                pkg += self._packet_ids[i].tobytes()
                pkg += self._packet_num[i].tobytes()
                pkg += np.packbits(self._digital_in[i, :]).tobytes()
                pkg += np.packbits(self._sync_in[i, :]).tobytes()
                pkg += self._frame_counter[i].tobytes()
                pkg += self._position[i, :].tobytes()
                pkg += self._traces[trace_idx].tobytes()
                pkg += np.packbits(self._digital_out[i, :]).tobytes()
                pkg += np.packbits(self._stimulator_status[i, :]).tobytes()
                pkg += b'\x00'*10
                pkg += self._keys_pressed[i, :].tobytes()

                assert len(pkg) == 432

                data_out.write(pkg)
        logger.info("Writing Axona settings file")
        with open(out_path+'.set', 'w') as settings_out:
            if self._settings is None:
                with open(self._set_file_path, 'r') as io_in:
                    settings_out.write(io_in.read())
            else:
                for key, val in self._settings.items():
                    settings_out.write(key + " " + val + "\n")

    def upsample(self) -> None:
        """Upsample data from 24 kHz to 48 kHz."""
        try:
            if self._mode_128ch:
                raise ValueError("128 channel mode and 48kHz sampling rate\
                     are incompatible")
            if int(self._settings['rawRate']) == 48000:
                raise ValueError("Data is already at 48kHz sampling rate")
        except ValueError as v:
            logger.exception(v)
        if self._traces is None:
            self._data_load_helper(load_traces=True)
        logger.info("Upsampling data to 48kHz")
        num_pkgs = int(self._packet_ids.shape[0]*2)
        packet_ids = np.zeros(num_pkgs, dtype='a4')
        self._packet_num = np.arange(num_pkgs, dtype=np.uint32) +\
            self._packet_num[0]
        digital_in = np.zeros((num_pkgs, 16), dtype=np.uint8)
        sync_in = np.zeros((num_pkgs, 16), dtype=np.uint8)
        frame_counter = np.zeros(num_pkgs, dtype=np.uint32)
        position = np.zeros((num_pkgs, 8), dtype=np.uint16)
        digital_out = np.zeros((num_pkgs, 16), dtype=np.uint8)
        stimulator_status = np.zeros((num_pkgs, 16), dtype=np.uint8)
        keys_pressed = np.zeros((num_pkgs, 2), dtype='a1')

        logger.info("Building missing data")
        for i in range(num_pkgs):
            if i % 2 and self._packet_ids[i//2] == b'ADU2':
                packet_ids[i] = b'ADU1'
                frame_counter[i] = frame_counter[i-2]
                position[i, :] = position[i-2, :]
            else:
                packet_ids[i] = b'ADU2'
                frame_counter[i] = self._frame_counter[i//2]
                position[i, :] = self._position[i//2, :]
            digital_in[i, :] = self._digital_in[i//2, :]
            digital_out[i, :] = self._digital_out[i//2, :]
            sync_in[i, :] = self._sync_in[i//2, :]
            stimulator_status[i, :] = self._stimulator_status[i//2, :]
            keys_pressed[i, :] = self._keys_pressed[i//2, :]

        self._num_pkgs = num_pkgs
        self._packet_ids = packet_ids
        self._digital_in = digital_in
        self._sync_in = sync_in
        self._frame_counter = frame_counter
        self._position = position
        self._digital_out = digital_out
        self._stimulator_status = stimulator_status
        self._keys_pressed = keys_pressed
        self._settings['rawRate'] = '48000'
        tmp_traces = np.rint(signal.resample_poly(self._traces, 2, 1))
        tmp_traces = tmp_traces.astype(np.int16)
        if self._traces_map_file is not None:
            self._traces = np.memmap(self._traces_map_file,
                                     shape=tmp_traces.shape,
                                     dtype=np.int16, mode='r+')
            self._traces[:] = tmp_traces[:]
            logger.info("Writing raw data to disk")
            self._traces.flush()
        else:
            self._traces = tmp_traces

    def _data_load_helper(self, load_traces: bool = False) -> None:
        """Load data in memory."""
        logger.info("Loading data from Axona raw file")
        with RawFile(self._raw_data_path) as raw_data:
            num_pkgs = len(raw_data)
            # Preallocate memory for all arrays except traces
            logger.info("Preallocating memory")
            self._packet_ids = np.zeros(num_pkgs, dtype='a4')
            self._packet_num = np.zeros(num_pkgs, dtype=np.uint32)
            self._digital_in = np.zeros((num_pkgs, 16), dtype=np.uint8)
            self._sync_in = np.zeros((num_pkgs, 16), dtype=np.uint8)
            self._frame_counter = np.zeros(num_pkgs, dtype=np.uint32)
            self._position = np.zeros((num_pkgs, 8), dtype=np.uint16)
            self._digital_out = np.zeros((num_pkgs, 16), dtype=np.uint8)
            self._stimulator_status = np.zeros((num_pkgs, 16), dtype=np.uint8)
            self._keys_pressed = np.zeros((num_pkgs, 2), dtype='a1')
            if load_traces:
                if not self._mode_128ch:
                    traces_shape = (num_pkgs*3, self._valid_channels.sum())
                else:
                    traces_shape = ((num_pkgs//2)*3,
                                    self._valid_channels.sum())
                if self._traces_map_file is None:
                    self._traces = np.zeros(traces_shape, dtype=np.int16)
                else:
                    # Create numpy memmap to save traces
                    self._traces = np.memmap(self._traces_map_file,
                                             shape=traces_shape,
                                             dtype=np.int16, mode='w+')
            pkg_idx = 0
            logger.info("Reading data from disk")
            for packet in raw_data:
                # Read packet
                (pkg_id, pkg_num, dig_in, snc_in, frm_ctr, pos_tracking, data,
                    dig_out, stim_status, keys) = RawFile.read_packet(packet)
                self._packet_ids[pkg_idx] = pkg_id
                self._packet_num[pkg_idx] = pkg_num
                self._digital_in[pkg_idx, :] = dig_in
                self._sync_in[pkg_idx, :] = snc_in
                self._frame_counter[pkg_idx] = frm_ctr
                self._position[pkg_idx, :] = pos_tracking
                self._digital_out[pkg_idx, :] = dig_out
                self._stimulator_status[pkg_idx, :] = stim_status
                self._keys_pressed[pkg_idx, :] = keys
                if load_traces:
                    if not self._mode_128ch:
                        data_idx = (
                            slice(pkg_idx*3, (pkg_idx+1)*3),
                            slice(None)
                        )
                    else:
                        channel_block = pkg_id.encode(encoding="ascii")
                        channel_block = np.frombuffer(channel_block,
                                                      dtype=np.uint8)[-1]
                        channel_block = np.unpackbits(channel_block)[2]
                        data_idx = (
                            slice((pkg_idx//2)*3, ((pkg_idx//2)+1)*3),
                            self._128ch_pk_slice[channel_block]
                        )
                    # Write data in output file
                    pk_data = data[self._traces_pk_slice]
                    self._traces[data_idx] = \
                        pk_data[:, self._valid_channels]
                # Advance the packet index
                pkg_idx += 1

    @property
    def packet_ids(self) -> np.ndarray:
        """Get packet IDs."""
        if self._packet_ids is None:
            self._data_load_helper()

        return self._packet_ids

    @property
    def packet_num(self) -> np.ndarray:
        """Get packet numbers."""
        if self._packet_num is None:
            self._data_load_helper()

        return self._packet_num

    @property
    def digital_in(self) -> np.ndarray:
        """Get digital input status."""
        if self._digital_in is None:
            self._data_load_helper()

        return self._digital_in

    @property
    def digital_out(self) -> np.ndarray:
        """Get digital output status."""
        if self._digital_out is None:
            self._data_load_helper()

        return self._digital_out

    @property
    def sync_in(self) -> np.ndarray:
        """Get sync status."""
        if self._sync_in is None:
            self._data_load_helper()

        return self._sync_in

    @property
    def frame_counter(self) -> np.ndarray:
        """Get frame counter data."""
        if self._frame_counter is None:
            self._data_load_helper()

        return self._frame_counter

    @property
    def position(self) -> np.ndarray:
        """Get position data."""
        if self._position is None:
            self._data_load_helper()

        return self._position

    @property
    def traces(self) -> np.ndarray:
        """Get voltage traces."""
        if self._traces is None:
            self._data_load_helper(load_traces=True)
        return self._traces

    @traces.setter
    def traces(self, data: np.ndarray) -> None:
        """Set voltage traces."""
        if self._traces is None:
            self._data_load_helper(load_traces=True)
        try:
            assert data.shape == self._traces.shape
        except AssertionError as e:
            logger.error("Data shape does not match traces shape")
            raise e
        self._traces[:] = data[:]

    @property
    def stimulator_status(self) -> np.ndarray:
        """Get stimulator status."""
        if self._stimulator_status is None:
            self._data_load_helper()

        return self._stimulator_status

    @property
    def keys_pressed(self) -> np.ndarray:
        """Get keys pressed."""
        if self._keys_pressed is None:
            self._data_load_helper()

        return self._keys_pressed

    @property
    def settings(self) -> Dict:
        """Get recording settings."""
        if not self._set_file_path.exists():
            raise FileNotFoundError("Can't open settings file")
        if self._settings is None:
            self._settings = read_set_file(self._set_file_path)

        return self._settings


def read_set_file(path: Union[str, Path]) -> Dict:
    """Read recording settings file.

    Args:
        path (Union[str, Path]): Path of the .set file to read

    Returns:
        Dict: Recording settings
    """
    try:
        with open(path, 'r') as fd:
            data = []
            for line in fd:
                data.append(tuple(line.rstrip('\n').split(" ", maxsplit=1)))
    except UnicodeDecodeError:
        with open(path, 'r', encoding='cp1252') as fd:
            data = []
            for line in fd:
                data.append(tuple(line.rstrip('\n').split(" ", maxsplit=1)))
    return dict(data)


def reconstruct_position(tracking_data: np.ndarray) -> Tuple[
        np.ndarray, np.ndarray
]:
    """Interpolate missing position data.

    Args:
        tracking_data (np.ndarray): Position tracking data

    Returns:
        time_axis (np.ndarray): timestamps
        reconstructed_position (np.ndarray): interpolated position
    """
    time_axis = np.arange(tracking_data.shape[0])/50.0
    valid_data = np.all(tracking_data[:, :4] != 1023, axis=1)
    invalid_data = ~valid_data

    valid_data = tracking_data[valid_data, :4]
    valid_times = time_axis[valid_data]
    interpolator = interpolate.Akima1DInterpolator(valid_times, valid_data)

    reconstructed_position = np.copy(tracking_data[:, :4])
    reconstructed_position[invalid_data, :] = \
        interpolator(time_axis[invalid_data])

    reconstructed_position = (
        reconstructed_position[:, :2]+reconstructed_position[:, 2:4])*0.5

    return time_axis, reconstructed_position


def clean_position(tracking_data: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Remove invalid position data and average big and small LED position.

    Args:
        tracking_data (np.ndarray): Position tracking data

    Returns:
        Tuple[np.ndarray, np.ndarray]: timestamps and interpolated position
    """
    time_axis = np.arange(tracking_data.shape[0])/50.0
    valid_data = np.all(tracking_data[:, :4] != 1023, axis=1)
    valid_data = tracking_data[valid_data, :4]
    valid_times = time_axis[valid_data]

    return valid_times, (valid_data[:, :2]+valid_data[:, 2:4])*0.5


def read_eeg(fname: Union[str, Path]) -> Tuple[dict, np.ndarray]:
    """Read Axona EEG file.

    Args:
        fname (Union[str, Path]): [description]

    Returns:
        Tuple[dict, np.ndarray]: [description]
    """
    fname = Path(fname)
    format = fname.suffix.lstrip('.')[:3]
    with fname.open('rb') as eeg_file:
        blk_size = 1024
        blk = eeg_file.read(blk_size)
        while b'data_start' not in blk:
            blk_size *= 2
            eeg_file.seek(0)
            blk = eeg_file.read(blk_size)
        md, _ = blk.split(b'data_start')
        offset = len(md) + 10
        eeg_file.seek(0)
        data = np.frombuffer(eeg_file.read()[offset:-12], dtype=np.int16)
    md_ascii = md.decode('ascii')
    md_ascii = md_ascii.strip('\r\n')
    metadata = md_ascii.split('\r\n')
    metadata_list = []
    for val in metadata:
        tmp = val.strip().split(maxsplit=1)
        if len(tmp) == 1:
            tmp.append('')
        try:
            tmp[1] = int(tmp[1])
        except ValueError:
            pass
        metadata_list.append(tuple(tmp))
    metadata = dict(metadata_list)

    assert data.size == metadata[f'num_{format.upper()}_samples']

    return metadata, data


def find_sessions(search_path):
    search_path = Path(search_path)
    sessions = []

    for session in search_path.glob("**/*.set"):
        session_files = session.parent.glob(session.stem + ".*")
        session_files = list(session_files)
        if len(session_files) == 1:
            continue
        elif len(session_files) == 2:
            session_type = 'RAW'
        else:
            session_type = 'TINT'

        settings = read_set_file(session)
        date = settings['trial_date'] + " " + settings['trial_time']
        date = datetime.strptime(date, "%A, %d %b %Y %H:%M:%S")
        sessions.append((date, session_type, session))

    return sorted(sessions, key=lambda session: session[0])
