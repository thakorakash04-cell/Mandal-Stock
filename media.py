"""Small, metadata-free inventory photos and persistent version-keyed caching."""
import io
from PIL import Image, ImageOps
import streamlit as st

MAX_PHOTO_BYTES=60_000
MAX_PHOTO_DIMENSION=720

def compress_photo(data):
    if not data:return None
    if len(data)>10_000_000:raise ValueError('Choose a photo under 10 MB.')
    with Image.open(io.BytesIO(data)) as source:
        if source.width*source.height>25_000_000:raise ValueError('Photo dimensions are too large. Choose a photo under 25 megapixels.')
        source=ImageOps.exif_transpose(source)
        rgba=source.convert('RGBA');image=Image.new('RGB',rgba.size,'white');image.paste(rgba,mask=rgba.getchannel('A'))
        image.thumbnail((MAX_PHOTO_DIMENSION,MAX_PHOTO_DIMENSION),Image.Resampling.LANCZOS)
        # New image + no EXIF argument strips location/camera metadata.
        for dimension in (720,600,480,360):
            image.thumbnail((dimension,dimension),Image.Resampling.LANCZOS)
            for quality in (72,60,48,36):
                out=io.BytesIO();image.save(out,format='JPEG',quality=quality,optimize=True)
                if len(out.getvalue())<=MAX_PHOTO_BYTES:return out.getvalue()
    raise ValueError('Could not reduce this photo enough. Please choose another image.')

@st.cache_data(persist='disk',show_spinner=False)
def cached_photo(database_url,item_id,photo_version,_uploaded=None):
    """No TTL: unchanged photos survive reruns, sessions and normal process restarts.

    The version is derived from stored bytes. _uploaded seeds the same cache key
    immediately after a successful write, avoiding a read-back from PostgreSQL.
    The database URL segregates caches but never appears in a cache filename.
    """
    if _uploaded is not None:return _uploaded
    from store import Store
    return Store(database_url).photo(item_id,photo_version)
