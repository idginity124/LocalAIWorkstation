import { t } from '../i18n';

export type GalleryItem = {
  filename: string; url: string; bytes: number; mtime: number;
  created_at: string; prompt: string; path?: string; mode?: string;
  seed?: number; steps?: number; cfg?: number; width?: number; height?: number; duration_seconds?: number;
};
export type ImageJob = { id: string; status: string; prompt: string; created_at: string; error?: string; result?: GalleryItem };
export const ACTIVE_IMAGE_JOBS = ['QUEUED','PREPARING','RUNNING','CANCELLING','CLEANUP'];

export function imageJobFeedback(job: ImageJob): { message: string; error: boolean } | null {
  if (job.status === 'FAILED' || job.status === 'RECOVERY_REQUIRED') return {message:job.error || t('Görsel üretimi başarısız oldu.'),error:true};
  if (job.status === 'INTERRUPTED') return {message:t('Görsel işi iptal edildi.'),error:false};
  return null;
}

export function validateImageSettings(seed: number, steps: number, cfg: number): void {
  if (!Number.isSafeInteger(seed) || seed < -1) throw new Error(t('Seed, -1 veya pozitif bir tam sayı olmalı.'));
  if (!Number.isInteger(steps) || steps < 1 || steps > 30 || !Number.isFinite(cfg) || cfg < .5 || cfg > 10) throw new Error(t('Adım 1–30, CFG 0,5–10 aralığında olmalı.'));
}

export function readOriginalImage(file: File): Promise<string> {
  if (!file.size || file.size > 12 * 1024**2) return Promise.reject(new Error(t('Görsel 12 MB altında olmalı.')));
  return new Promise((resolve,reject) => {
    const reader=new FileReader();
    reader.onload=() => typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error(t('Görsel okunamadı.')));
    reader.onerror=() => reject(new Error(t('Görsel okunamadı.')));
    reader.readAsDataURL(file);
  });
}

export function imageOutputPath(image: GalleryItem, outputDir?: string): string {
  if (image.path) return image.path;
  if (outputDir) return outputDir.replace(/\/$/,'') + '/' + image.filename;
  throw new Error(t('Dosya yolu alınamadı.'));
}
