export type VoiceProfile = { id: string; name: string; transcript: string; audio: Blob; filename: string; createdAt: string };

async function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('local-ai-voices', 1);
    request.onupgradeneeded = () => { request.result.createObjectStore('voices', { keyPath: 'id' }); };
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
}

async function operation<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction('voices', mode);
    const request = action(transaction.objectStore('voices'));
    transaction.oncomplete = () => { db.close(); resolve(request.result); };
    transaction.onabort = () => { db.close(); reject(transaction.error); };
    transaction.onerror = () => { db.close(); reject(transaction.error); };
  });
}

export const listVoices = () => operation<VoiceProfile[]>('readonly', store => store.getAll());
export const saveVoice = (voice: VoiceProfile) => operation('readwrite', store => store.put(voice));
export const deleteVoice = (id: string) => operation('readwrite', store => store.delete(id));
