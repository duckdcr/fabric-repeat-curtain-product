"""Check bundled dependencies and assets without rendering or modifying files."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))


def check() -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10+ is required')
    import numpy as np
    import PIL
    from PIL import Image, features
    import weave8
    import quilt_cut
    import complete_repeat
    import render_curtain_product
    root = Path(__file__).resolve().parents[1]
    for module in (weave8, quilt_cut, complete_repeat, render_curtain_product):
        if Path(module.__file__).resolve().parent != root / 'scripts':
            raise RuntimeError(f'External renderer was imported: {module.__file__}')
    if weave8.ASSET_DIR.resolve() != root / 'assets':
        raise RuntimeError('External assets directory selected')
    if not features.check('webp'):
        raise RuntimeError('Pillow must support WebP')
    sizes = []
    for name in ('mask.png', 'double-pinch-template.png', 'uv-y.png'):
        with Image.open(root / 'assets' / name) as image:
            sizes.append(image.size)
            image.verify()
    uv = np.load(root / 'assets' / 'uvx_fixed.npy', allow_pickle=False)
    if len(set(sizes)) != 1 or uv.shape != (sizes[0][1], sizes[0][0]):
        raise RuntimeError('Template/UV shapes do not match')
    if sizes[0] != (int(weave8.BASE), int(weave8.BASE)):
        raise RuntimeError('Template dimensions do not match renderer base')
    print(f'OK: Python {sys.version.split()[0]}, NumPy {np.__version__}, Pillow {PIL.__version__}; all renderers/assets are local')


if __name__ == '__main__':
    check()
