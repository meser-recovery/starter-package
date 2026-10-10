"""Pixel checks for the two local B02 corrections in the delivered MP4."""
from __future__ import annotations

import subprocess
from pathlib import Path


def cloud_hold(video: Path, common_seconds: float) -> dict:
    def crop(second):
        return subprocess.check_output([
            'ffmpeg', '-v', 'error', '-xerror', '-ss', str(second), '-i', str(video),
            '-frames:v', '1', '-vf', 'crop=520:358:1040:365,scale=130:89:flags=area,format=gray',
            '-f', 'rawvideo', 'pipe:1'])
    reference = crop(common_seconds-.1)
    if len(reference) != 130*89 or sum(x < 200 for x in reference)/len(reference) < .25:
        raise RuntimeError('B02 cloud is not fully visible before the common-file transition')
    samples = [common_seconds-1.45+i*.3 for i in range(5)]
    differences = []
    for second in samples:
        frame = crop(second)
        delta = sum(abs(a-b) for a, b in zip(frame, reference))/len(reference)
        if len(frame) != len(reference) or delta > 2:
            raise RuntimeError(f'B02 cloud does not remain fully visible for 1.45 seconds ({second:.3f}s)')
        differences.append(round(delta, 4))
    return {'fully_visible_hold_verified_seconds': 1.45, 'sample_seconds': samples,
            'crop_mean_difference_from_opaque_cloud': differences,
            'transition_to_common_file_seconds': common_seconds}


def single_track_axis(video: Path, ranges: list[tuple[float, float]]) -> dict:
    checked = 0
    for start, end in ranges:
        first, last = round(start*30)+3, round(end*30)-2
        raw = subprocess.check_output([
            'ffmpeg', '-v', 'error', '-xerror', '-i', str(video),
            '-vf', f'select=between(n\\,{first}\\,{last}),crop=50:70:376:560,format=gray',
            '-vsync', '0', '-f', 'rawvideo', 'pipe:1'])
        size = 50*70
        if len(raw) != (last-first+1)*size:
            raise RuntimeError('B02 axis check has incomplete decoded frames')
        for index in range(last-first+1):
            frame = raw[index*size:(index+1)*size]
            rows = [sum(frame[y*50:(y+1)*50])/50 < 234 for y in range(70)]
            groups = sum(value and (y == 0 or not rows[y-1]) for y, value in enumerate(rows))
            if groups != 1:
                raise RuntimeError(f'B02 translator has {groups} horizontal bands at {(first+index)/30:.3f}s')
        checked += last-first+1
    return {'decoded_frames_checked': checked, 'horizontal_axis_groups_per_frame': 1,
            'checked_ranges_seconds': ranges}


def verify(video: Path, common_seconds: float, ranges: list[tuple[float, float]]) -> dict:
    return {'status': 'PASS', 'source': 'decoded delivered MP4 pixels',
            'cloud': cloud_hold(video, common_seconds),
            'translator_axis': single_track_axis(video, ranges)}
