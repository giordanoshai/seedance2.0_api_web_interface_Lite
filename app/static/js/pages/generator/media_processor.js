/**
 * Client-side video processing using ffmpeg.wasm
 * Automatically compresses videos with a pixel count > 921600 (1280x720) to fit within limits.
 */

const FFmpegWASM = window.FFmpegWASM || null;
const FFmpegUtil = window.FFmpegUtil || null;

let ffmpegInitPromise = null; // 缓存 Promise 而不是实例，防止并发初始化

function getFFmpeg() {
    if (ffmpegInitPromise) return ffmpegInitPromise;

    ffmpegInitPromise = (async () => {
        try {
            const { FFmpeg } = window.FFmpegWASM;
            const ffmpeg = new FFmpeg();

            ffmpeg.on('log', ({ message }) => {
                console.log('[FFmpeg]', message);
            });

            console.log('[FFmpeg] Requesting load...');
            const baseURL = '/static/js/lib';
            await ffmpeg.load({
                coreURL: await FFmpegUtil.toBlobURL(`${baseURL}/ffmpeg-core.js`, 'text/javascript'),
                wasmURL: await FFmpegUtil.toBlobURL(`${baseURL}/ffmpeg-core.wasm`, 'application/wasm')
            });
            console.log('[FFmpeg] Loaded successfully');

            return ffmpeg;
        } catch (error) {
            console.error("FFmpeg initialization failed:", error);
            ffmpegInitPromise = null; // 失败后重置，允许后续重试
            throw error;
        }
    })();

    return ffmpegInitPromise;
}

/**
 * Parses video dimensions from file locally without uploading
 */
function getVideoDimensions(file) {
    return new Promise((resolve, reject) => {
        const url = URL.createObjectURL(file);
        const video = document.createElement('video');
        video.preload = 'metadata';

        video.onloadedmetadata = () => {
            video.removeAttribute('src');
            URL.revokeObjectURL(url);
            resolve({
                width: video.videoWidth,
                height: video.videoHeight,
                pixelCount: video.videoWidth * video.videoHeight
            });
        };
        video.onerror = () => {
            video.removeAttribute('src');
            URL.revokeObjectURL(url);
            reject(new Error("Unable to read video metadata"));
        };
        video.src = url;
    });
}

/**
 * Compresses the video if its pixel count exceeds the maximum limit
 * Limit: 927408 (roughly 1280x720)
 * Applies to doubao-seedance-2-0 r2v mode
 */
window.processVideoIfOversized = async function (file, maxSize = 921600, onProgress) {
    try {
        const dims = await getVideoDimensions(file);

        if (dims.pixelCount <= maxSize) {
            return file;
        }

        console.log(`[VideoProcessor] Video ${dims.width}x${dims.height} exceeds ${maxSize} limit, resizing...`);

        let scaleRatio = Math.sqrt(maxSize / dims.pixelCount);
        let newWidth = Math.floor(dims.width * scaleRatio);
        let newHeight = Math.floor(dims.height * scaleRatio);

        // 确保是偶数 (更稳妥的位运算写法)
        newWidth = Math.floor(newWidth / 2) * 2;
        newHeight = Math.floor(newHeight / 2) * 2;

        console.log('[VideoProcessor] Loading FFmpeg...');
        const ffmpeg = await getFFmpeg();
        console.log('[VideoProcessor] FFmpeg loaded');
        const { fetchFile } = window.FFmpegUtil;

        // 动态生成文件名，防止并发处理时覆盖
        const uniqueId = Date.now() + '_' + Math.random().toString(36).substring(2, 9);
        const inputName = `in_${uniqueId}.mp4`;
        const outputName = `out_${uniqueId}.mp4`;

        const progressHandler = ({ progress, time }) => {
            if (onProgress) {
                onProgress(progress);
            }
        };

        ffmpeg.on('progress', progressHandler);

        // 使用 try...finally 确保不论成功失败都能释放内存
        try {
            console.log(`[VideoProcessor] Writing input file: ${inputName}`);
            await ffmpeg.writeFile(inputName, await fetchFile(file));
            console.log('[VideoProcessor] Input file written, starting exec...');

            // 加入 -pix_fmt yuv420p 保证最大兼容性
            const exitCode = await ffmpeg.exec([
                '-i', inputName,
                '-vf', `scale=${newWidth}:${newHeight}`,
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                '-crf', '23',
                '-preset', 'ultrafast',
                '-c:a', 'copy',
                outputName
            ]);

            if (exitCode !== 0) {
                throw new Error(`FFmpeg exited with code ${exitCode}`);
            }

            const outputData = await ffmpeg.readFile(outputName);

            return new File([outputData.buffer], file.name, {
                type: 'video/mp4'
            });

        } finally {
            ffmpeg.off('progress', progressHandler);
            // 无论执行结果如何，清理虚拟文件系统中的文件，防止内存泄漏
            try { await ffmpeg.deleteFile(inputName); } catch (e) { }
            try { await ffmpeg.deleteFile(outputName); } catch (e) { }
        }

    } catch (error) {
        console.error("Video processing failed:", error);
        throw new Error("Failed to process video: " + error.message);
    }
};