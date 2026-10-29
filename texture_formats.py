from __future__ import annotations

from array import array
from pathlib import Path
import struct
from typing import List, Tuple

import bpy


class DDSFormatError(ValueError):
    """Raised when a DDS image is malformed or uses an unsupported format."""


def _rgb565(value: int) -> Tuple[int, int, int]:
    red = (value >> 11) & 0x1F
    green = (value >> 5) & 0x3F
    blue = value & 0x1F
    return (red * 255 // 31, green * 255 // 63, blue * 255 // 31)


def _color_block(data: bytes, *, allow_transparency: bool):
    color0, color1, indices = struct.unpack("<HHI", data)
    colors = [(*_rgb565(color0), 255), (*_rgb565(color1), 255)]
    if color0 > color1 or not allow_transparency:
        colors.extend(
            (
                tuple((2 * colors[0][i] + colors[1][i]) // 3 for i in range(3))
                + (255,),
                tuple((colors[0][i] + 2 * colors[1][i]) // 3 for i in range(3))
                + (255,),
            )
        )
    else:
        colors.extend(
            (
                tuple((colors[0][i] + colors[1][i]) // 2 for i in range(3))
                + (255,),
                (0, 0, 0, 0),
            )
        )
    return [colors[(indices >> (2 * index)) & 3] for index in range(16)]


def _alpha_block(data: bytes) -> List[int]:
    alpha0, alpha1 = data[0], data[1]
    if alpha0 > alpha1:
        palette = [
            alpha0,
            alpha1,
            *(
                ((7 - index) * alpha0 + index * alpha1) // 7
                for index in range(1, 7)
            ),
        ]
    else:
        palette = [
            alpha0,
            alpha1,
            *(
                ((5 - index) * alpha0 + index * alpha1) // 5
                for index in range(1, 5)
            ),
            0,
            255,
        ]
    indices = int.from_bytes(data[2:8], "little")
    return [palette[(indices >> (3 * index)) & 7] for index in range(16)]


def _decode_block(data: bytes, compression: str):
    if compression == "BC1":
        return _color_block(data, allow_transparency=True)
    if compression == "BC2":
        alpha_bits = int.from_bytes(data[:8], "little")
        colors = _color_block(data[8:16], allow_transparency=False)
        return [
            (*color[:3], ((alpha_bits >> (4 * index)) & 0xF) * 17)
            for index, color in enumerate(colors)
        ]
    if compression == "BC3":
        alphas = _alpha_block(data[:8])
        colors = _color_block(data[8:16], allow_transparency=False)
        return [
            (*color[:3], alphas[index])
            for index, color in enumerate(colors)
        ]
    raise DDSFormatError(f"Unsupported DDS compression: {compression}")


def _decode_dds(data: bytes) -> Tuple[int, int, bytes]:
    if len(data) < 128 or data[:4] != b"DDS ":
        raise DDSFormatError("Invalid or truncated DDS header")
    header_size, flags, height, width, pitch = struct.unpack_from("<5I", data, 4)
    if header_size != 124 or width == 0 or height == 0:
        raise DDSFormatError("Invalid DDS header dimensions or size")
    pixel_format_size, pixel_flags = struct.unpack_from("<2I", data, 76)
    if pixel_format_size != 32:
        raise DDSFormatError("Invalid DDS pixel format header")

    fourcc = data[84:88]
    pixel_offset = 128
    compression = None
    if pixel_flags & 0x4:
        if fourcc == b"DXT1":
            compression = "BC1"
        elif fourcc in (b"DXT2", b"DXT3"):
            compression = "BC2"
        elif fourcc in (b"DXT4", b"DXT5"):
            compression = "BC3"
        elif fourcc == b"DX10":
            if len(data) < 148:
                raise DDSFormatError("Truncated DDS DX10 header")
            dxgi_format = struct.unpack_from("<I", data, 128)[0]
            compression = {
                70: "BC1",
                71: "BC1",
                72: "BC1",
                73: "BC2",
                74: "BC2",
                75: "BC2",
                76: "BC3",
                77: "BC3",
                78: "BC3",
            }.get(dxgi_format)
            if compression is None:
                raise DDSFormatError(
                    f"Unsupported DDS DXGI format: {dxgi_format}"
                )
            pixel_offset += 20
        else:
            raise DDSFormatError(
                f"Unsupported DDS compression code: {fourcc!r}"
            )

    pixels = bytearray(width * height * 4)
    if compression:
        block_bytes = 8 if compression == "BC1" else 16
        blocks_x = (width + 3) // 4
        blocks_y = (height + 3) // 4
        required = blocks_x * blocks_y * block_bytes
        if len(data) < pixel_offset + required:
            raise DDSFormatError("Truncated DDS pixel data")
        offset = pixel_offset
        for block_y in range(blocks_y):
            for block_x in range(blocks_x):
                block = _decode_block(
                    data[offset : offset + block_bytes],
                    compression,
                )
                offset += block_bytes
                for local_y in range(4):
                    for local_x in range(4):
                        x = block_x * 4 + local_x
                        y = block_y * 4 + local_y
                        if x >= width or y >= height:
                            continue
                        source_index = local_y * 4 + local_x
                        target_index = (y * width + x) * 4
                        pixels[target_index : target_index + 4] = bytes(
                            block[source_index]
                        )
    else:
        bits_per_pixel = struct.unpack_from("<I", data, 88)[0]
        if bits_per_pixel not in {16, 24, 32}:
            raise DDSFormatError(
                f"Unsupported uncompressed DDS pixel depth: {bits_per_pixel}"
            )
        bytes_per_pixel = bits_per_pixel // 8
        minimum_pitch = width * bytes_per_pixel
        row_pitch = (
            pitch
            if flags & 0x8 and pitch >= minimum_pitch
            else minimum_pitch
        )
        required = row_pitch * height
        if len(data) < pixel_offset + required:
            raise DDSFormatError("Truncated DDS pixel data")
        red_mask, green_mask, blue_mask, alpha_mask = struct.unpack_from(
            "<4I", data, 92
        )
        for y in range(height):
            for x in range(width):
                offset = (
                    pixel_offset
                    + y * row_pitch
                    + x * bytes_per_pixel
                )
                value = int.from_bytes(data[offset : offset + bytes_per_pixel], "little")
                channels = []
                for mask, default in (
                    (red_mask, 0),
                    (green_mask, 0),
                    (blue_mask, 0),
                    (alpha_mask, 255),
                ):
                    if not mask:
                        channels.append(default)
                        continue
                    shift = (mask & -mask).bit_length() - 1
                    maximum = mask >> shift
                    channels.append(((value & mask) >> shift) * 255 // maximum)
                target_index = (y * width + x) * 4
                pixels[target_index : target_index + 4] = bytes(channels)
    return width, height, bytes(pixels)


def _load_dds(path: Path, *, check_existing: bool):
    image_key = str(path.resolve())
    stat = path.stat()
    existing = None
    if check_existing:
        existing = next(
            (
                image
                for image in bpy.data.images
                if image.get("_glm_md3_dds_path") == image_key
            ),
            None,
        )
        if (
            existing is not None
            and existing.get("_glm_md3_dds_mtime_ns") == stat.st_mtime_ns
            and existing.get("_glm_md3_dds_size") == stat.st_size
        ):
            return existing

    width, height, rgba = _decode_dds(path.read_bytes())
    if existing is not None and (existing.size[0], existing.size[1]) == (
        width,
        height,
    ):
        existing.pixels.foreach_set(
            array("f", (channel / 255 for channel in rgba))
        )
        existing["_glm_md3_dds_mtime_ns"] = stat.st_mtime_ns
        existing["_glm_md3_dds_size"] = stat.st_size
        return existing

    image = bpy.data.images.new(
        name=path.name,
        width=width,
        height=height,
        alpha=True,
    )
    image.pixels.foreach_set(
        array("f", (channel / 255 for channel in rgba))
    )
    image.colorspace_settings.name = "sRGB"
    image["_glm_md3_dds_path"] = image_key
    image["_glm_md3_dds_mtime_ns"] = stat.st_mtime_ns
    image["_glm_md3_dds_size"] = stat.st_size
    if existing is not None:
        existing.user_remap(image)
    return image


def load_texture(path: str | Path, *, check_existing: bool = True):
    texture_path = Path(path)
    if texture_path.suffix.lower() == ".dds":
        return _load_dds(texture_path, check_existing=check_existing)
    image = bpy.data.images.load(
        str(texture_path),
        check_existing=check_existing,
    )
    image.reload()
    return image
