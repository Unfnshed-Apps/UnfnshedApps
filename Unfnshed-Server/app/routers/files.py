"""File upload/download API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import FileResponse

from ..auth import verify_api_key
from ..file_storage import FileStorage
from ..models import FileInfo, FileUploadResponse

router = APIRouter(prefix="/files", tags=["files"])


def get_file_storage() -> FileStorage:
    """Dependency to get file storage instance."""
    return FileStorage()


@router.post("/component-dxf", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_component_dxf(
    file: UploadFile = File(...),
    _: str = Depends(verify_api_key),
    storage: FileStorage = Depends(get_file_storage)
):
    """
    Upload a component DXF file.

    The file will be validated and stored on the server.
    Filenames are sanitized to prevent security issues.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    try:
        result = storage.save_component_dxf(file.file, file.filename)
        return FileUploadResponse(
            filename=result["filename"],
            size=result["size"],
            checksum=result["checksum"],
            message="File uploaded successfully"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")


@router.get("/component-dxf", response_model=list[FileInfo])
async def list_component_dxf(
    _: str = Depends(verify_api_key),
    storage: FileStorage = Depends(get_file_storage)
):
    """List all component DXF files on the server."""
    files = storage.list_component_dxf()
    return [FileInfo(**f) for f in files]


@router.get("/component-dxf/{filename}")
async def download_component_dxf(
    filename: str,
    _: str = Depends(verify_api_key),
    storage: FileStorage = Depends(get_file_storage)
):
    """
    Download a component DXF file.

    Returns the file content with appropriate headers for download.
    """
    try:
        file_path = storage.get_component_dxf_path(filename)
        return FileResponse(
            path=file_path,
            filename=file_path.name,
            media_type="application/dxf"
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")


@router.head("/component-dxf/{filename}")
async def check_component_dxf(
    filename: str,
    _: str = Depends(verify_api_key),
    storage: FileStorage = Depends(get_file_storage)
):
    """
    Check if a component DXF file exists.

    Returns 200 if file exists, 404 if not.
    Useful for clients to check before downloading.
    """
    if storage.component_dxf_exists(filename):
        return {"exists": True}
    raise HTTPException(status_code=404, detail=f"File not found: {filename}")


@router.delete("/component-dxf/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_component_dxf(
    filename: str,
    _: str = Depends(verify_api_key),
    storage: FileStorage = Depends(get_file_storage)
):
    """Delete a component DXF file."""
    if not storage.delete_component_dxf(filename):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")


# ==================== Nesting DXF Endpoints ====================


@router.post("/nesting-dxf", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_nesting_dxf(
    file: UploadFile = File(...),
    _: str = Depends(verify_api_key),
    storage: FileStorage = Depends(get_file_storage)
):
    """Upload a nesting layout DXF file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    try:
        result = storage.save_nesting_dxf(file.file, file.filename)
        return FileUploadResponse(**result, message="File uploaded successfully")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/nesting-dxf", response_model=list[FileInfo])
async def list_nesting_dxf(
    _: str = Depends(verify_api_key),
    storage: FileStorage = Depends(get_file_storage)
):
    """List all nesting layout DXF files."""
    return [FileInfo(**f) for f in storage.list_nesting_dxf()]


@router.get("/nesting-dxf/{filename}")
async def download_nesting_dxf(
    filename: str,
    _: str = Depends(verify_api_key),
    storage: FileStorage = Depends(get_file_storage)
):
    """Download a nesting layout DXF file."""
    try:
        file_path = storage.get_nesting_dxf_path(filename)
        return FileResponse(path=file_path, filename=file_path.name, media_type="application/dxf")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")


@router.delete("/nesting-dxf/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_nesting_dxf(
    filename: str,
    _: str = Depends(verify_api_key),
    storage: FileStorage = Depends(get_file_storage)
):
    """Delete a nesting layout DXF file."""
    if not storage.delete_nesting_dxf(filename):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")


# ==================== G-code Endpoints ====================


@router.post("/gcode", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_gcode(
    file: UploadFile = File(...),
    _: str = Depends(verify_api_key),
    storage: FileStorage = Depends(get_file_storage)
):
    """Upload a G-code file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    try:
        result = storage.save_gcode(file.file, file.filename)
        return FileUploadResponse(**result, message="File uploaded successfully")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/gcode", response_model=list[FileInfo])
async def list_gcode(
    _: str = Depends(verify_api_key),
    storage: FileStorage = Depends(get_file_storage)
):
    """List all G-code files."""
    return [FileInfo(**f) for f in storage.list_gcode()]


@router.get("/gcode/{filename}")
async def download_gcode(
    filename: str,
    _: str = Depends(verify_api_key),
    storage: FileStorage = Depends(get_file_storage)
):
    """Download a G-code file."""
    try:
        file_path = storage.get_gcode_path(filename)
        return FileResponse(path=file_path, filename=file_path.name, media_type="text/plain")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")


@router.delete("/gcode/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gcode(
    filename: str,
    _: str = Depends(verify_api_key),
    storage: FileStorage = Depends(get_file_storage)
):
    """Delete a G-code file."""
    if not storage.delete_gcode(filename):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
