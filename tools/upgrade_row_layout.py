"""Static layout of the core badge and the flashing price in protopowerpurchase.gfx."""
import struct

from full_resources import edit_text_parts, tag_bytes
from resources import p32, rect_end, swf_tags


# Coordinates are in twips (20 per UI pixel). The row has a common right
# edge for the ordinary price and the separate new-upgrade animation.
BADGE_X = -130
DECORATION_SCALE = 11 / 32
TEXT_RECTS = {
    8: ((-40, 2388, -40, 673), (-2812, 2388, -40, 673)),  # flashing price
    14: ((-40, 3092, -40, 567), (1066, 1986, -40, 567)),  # centred badge
    15: ((-40, 3092, -40, 567), (1066, 1986, -40, 567)),  # highlighted badge
}

# The original-width badge occupies its own column. Bounds are local to each
# field. The flashing copy has a different origin from the ordinary row.
NAME_FIELDS = {6, 7, 19, 38}
PRICE_FIELDS = {5, 8, 18, 37}
FULL_WIDTH_BADGE_X = 310
FULL_WIDTH_RECTS = {
    **{i: ((-40, right, -40, 673), (-180, 4140, -40, 673))
       for i, right in ((6, 8395), (7, 8670), (19, 8435), (38, 8395))},
    **{i: ((-2980, 2220, -40, 673), (-1660, 2260, -40, 673)) for i in (5, 18, 37)},
    8: ((-40, 2388, -40, 673), (-1492, 2428, -40, 673)),
    14: TEXT_RECTS[14],
    15: TEXT_RECTS[15],
}


def _signed_vector(values, width=None):
    if width is None:
        width = 0
        if any(values):
            width = 1 + max((v if v >= 0 else ~v).bit_length() for v in values)
    mask = (1 << width) - 1
    return f'{width:05b}' + (''.join(f'{v & mask:0{width}b}' for v in values) if width else '')


def _bytes(bits):
    bits += '0' * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, 'big')


def _matrix(x, y=0, scale_x=65536, scale_y=65536):
    scale = '0' if (scale_x, scale_y) == (65536, 65536) else '1' + _signed_vector((scale_x, scale_y))
    return _bytes(scale + '0' + _signed_vector((x, y)))  # no rotation or shear


def _place_row_badge(x):
    prefix = struct.pack('<BHH', 0x26, 27, 16)
    name = b'mcCoreUpgrade\0'
    return [(prefix + _matrix(2115, -18) + name, prefix + _matrix(x, -18) + name)]


def _placements():
    # The two badge frames have the same three layers of decoration. Compress
    # those layers around the local origin, so that both text placements retain
    # their original scale, centre, outline and glow.
    badge = []
    for depth, symbol, normal_x, highlight_x, scale_y in (
        (1, 12, 72, 67, 60621), (3, 12, -183, -188, 60621), (5, 13, 5, 0, 65536)
    ):
        create = struct.pack('<BHH', 6, depth, symbol)
        move = struct.pack('<BH', 5, depth)
        for prefix, x in ((create, normal_x), (move, highlight_x)):
            before = _matrix(x, scale_y=scale_y)
            after = _matrix(round(x * DECORATION_SCALE), scale_x=round(65536 * DECORATION_SCALE), scale_y=scale_y)
            badge.append((prefix + before, prefix + after))
    return {16: badge, 39: _place_row_badge(BADGE_X)}


def _tag(code, payload, original):
    if (int.from_bytes(original[:2], 'little') & 63) == 63 or len(payload) >= 63:
        return tag_bytes(code, payload)
    return struct.pack('<H', code << 6 | len(payload)) + payload


def _column_type(payload, price, restore):
    # DefineEditText has both a native height and an initial HTML format.
    # The engine can set plain text after initialization, so update both.
    end = rect_end(payload, 2)
    if not payload[end] & 1 or payload[end + 1] & 128:
        raise ValueError('Unexpected upgrade field font format')
    at, markup = edit_text_parts(payload)
    old, new = ('0.000000', '2.000000') if restore else ('2.000000', '0.000000')
    tracking = f'letterSpacing="{old}"'
    if markup.count(tracking) != 1:
        raise ValueError('Unexpected upgrade field letter spacing')
    markup = markup.replace(tracking, f'letterSpacing="{new}"')
    if price:
        before, after = (19, 21) if restore else (21, 19)
        height_at = end + 4  # flags and font ID
        if (struct.unpack_from('<H', payload, height_at)[0] != 20 * before
                or markup.count(f'size="{before}"') != 1):
            raise ValueError('Unexpected upgrade price font size')
        payload = payload[:height_at] + struct.pack('<H', 20 * after) + payload[height_at + 2:]
        markup = markup.replace(f'size="{before}"', f'size="{after}"')
    return payload[:at] + markup.encode('utf-8') + b'\0'


def fit_upgrade_row(movie, restore=False, revision=1):
    """Apply or reverse one release's static layout on the widened-price movie."""
    if revision == 1:
        rects, timeline = TEXT_RECTS, _placements()
    elif revision == 2:
        rects, timeline = FULL_WIDTH_RECTS, {39: _place_row_badge(FULL_WIDTH_BADGE_X)}
    else:
        raise ValueError(f'Unknown upgrade layout revision {revision}')
    prefix, tags = swf_tags(movie)
    parts = []
    seen_fields, seen_sprites = set(), set()
    for code, payload, raw in tags:
        if code in (37, 39):
            symbol = int.from_bytes(payload[:2], 'little')
            if code == 37 and symbol in rects:
                old, new = rects[symbol][::-1] if restore else rects[symbol]
                width = 15 if symbol in NAME_FIELDS else 13
                expected = _bytes(_signed_vector(old, width))
                if payload[2:2 + len(expected)] != expected or symbol in seen_fields:
                    raise ValueError(f'Unexpected upgrade text bounds for {symbol}')
                seen_fields.add(symbol)
                payload = payload[:2] + _bytes(_signed_vector(new, width)) + payload[2 + len(expected):]
                if revision == 2 and symbol in NAME_FIELDS | PRICE_FIELDS:
                    payload = _column_type(payload, symbol in PRICE_FIELDS, restore)
                raw = _tag(code, payload, raw)
            if code == 39 and symbol in timeline:
                changes = dict((after, before) if restore else (before, after) for before, after in timeline[symbol])
                body = b'\x08\x00\x00\x00\x01\x00' + payload[4:]
                children = swf_tags(b'FWS\x08' + p32(8 + len(body)) + body)[1]
                revised = []
                for child_code, child_payload, child_raw in children:
                    if child_code == 26 and child_payload in changes:
                        child_raw = _tag(child_code, changes.pop(child_payload), child_raw)
                    revised.append(child_raw)
                if changes or symbol in seen_sprites:
                    raise ValueError(f'Unexpected upgrade row timeline for {symbol}')
                seen_sprites.add(symbol)
                raw = _tag(code, payload[:4] + b''.join(revised), raw)
        parts.append(raw)
    if seen_fields != rects.keys() or seen_sprites != timeline.keys():
        raise ValueError('Missing upgrade row symbols')
    body = b''.join(parts)
    return prefix[:4] + p32(len(prefix) + len(body)) + prefix[8:] + body
