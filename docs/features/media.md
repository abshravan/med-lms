# Feature 3 — Media (upload & playback)

Status: **complete**. Backend, frontend, validation, error handling, loading
states, tests, and documentation all shipped.

---

## 1. Scope, and what was deliberately deferred

**Shipped:** direct-to-storage uploads, server-verified confirmation, per-kind
policy (type + size), attaching video to lessons and cover images to courses,
short-lived signed playback, and a video player.

**Deferred: HLS transcoding.** The original roadmap entry was "R2 upload, HLS
transcode, signed playback". Transcoding needs `ffmpeg` and a background worker,
and it is a feature in its own right — an encoding ladder, a job queue, retry
semantics, and progress reporting. Bundling it here would have produced two
half-features instead of one complete one.

The deferral is cheap because the seam is already in place: `PlaybackTicket` is
an object rather than a bare URL string, so returning a manifest URL plus a
different credential shape does not change the client contract. What changes when
HLS lands is documented in §6.

Lesson **attachments** (PDFs) have their `MediaKind` and policy defined but no UI:
they belong with the notes feature, which is where students will encounter them.

---

## 2. The central decision: bytes never touch the API

Three upload designs were considered.

| Approach | Verdict |
| --- | --- |
| **Presigned direct upload** ✅ | Chosen. The API issues a short-lived credential; the browser PUTs straight to R2. Two small JSON round-trips per upload, so upload capacity scales with the object store, not with API workers. |
| Proxy through the API | Rejected. A 500 MB lecture would occupy a request slot for minutes and sit in the container's memory or disk. Upload throughput would become a function of API capacity — the worst possible coupling. |
| Resumable / multipart (tus, S3 multipart) | Deferred. Genuinely better for multi-gigabyte files on flaky connections, but it needs part tracking, an assembly step, and cleanup of abandoned parts. **The upgrade path when authors start reporting failed large uploads.** |

### The consequence: confirmation cannot be trusted

Because the API never sees the bytes, it does not know when — or whether — an
upload finished. The client has to say so, and a client's word is not evidence.

So `POST /uploads/{id}/confirm` **HEADs the object in storage** before marking an
asset ready, and reads the real size back. A client that skips the upload and
calls confirm anyway gets a `409`, not a lesson whose video 404s for every
student. This is the single most important behaviour in the feature, and it has a
dedicated test.

### The gap this leaves, and the compensating control

**A presigned PUT cannot enforce a maximum object size.** Only a POST policy can,
and POST policies are awkward to use from a browser with arbitrary binary bodies.
So a client that requests a ticket for a 1 MB image can upload 500 MB to it.

The compensating control is at confirmation: the real size is checked against the
per-kind ceiling, and an oversized object is **deleted from storage** before the
asset is marked failed. Deleting first matters — an oversized object left behind
is billed for and still reachable by anyone holding the upload URL.

---

## 3. Security properties

| Property | Mechanism | Test |
| --- | --- | --- |
| Client cannot choose the object key | Keys are `{kind}/{yyyy}/{mm}/{uuid}{ext}`, generated server-side | `test_upload_ticket_is_issued_with_a_server_generated_key` |
| Extension cannot be spoofed | Derived from the **declared content type**, never the filename — `lecture.mp4.html` cannot become HTML | `TestStorageKeys::test_extension_comes_from_the_content_type` |
| Content type is bound to the credential | Signed into the presigned URL (`X-Amz-SignedHeaders=content-type;host`) | `test_upload_url_binds_the_content_type` |
| Type allowlist per kind | `ALLOWED_CONTENT_TYPES`; PDF-only for attachments (Office formats carry macros) | `test_upload_rejects_a_disallowed_content_type` |
| Size ceiling per kind | A cover image cannot smuggle a 2 GB upload | `test_a_cover_image_uses_the_image_size_ceiling` |
| Oversized uploads are removed | Verified and deleted at confirmation | `test_oversized_upload_is_deleted_on_confirmation` |
| Unconfirmed assets cannot be attached | Attachment requires `ready` | `test_attaching_an_unconfirmed_asset_is_rejected` |
| Kind cannot be mismatched | A cover attached as a lesson video is rejected | `test_attaching_a_cover_image_as_a_video_is_rejected` |
| Playback respects catalogue visibility | Draft courses stay unplayable | `test_playback_is_unavailable_for_a_draft_course` |
| Playback requires verification | `VerifiedUserDep` | `test_playback_requires_a_verified_email` |
| No enumeration of which lessons have video | Missing video returns `404`, same as a missing lesson | `test_playback_for_a_lesson_without_a_video_is_not_found` |
| Local backend cannot be replayed across methods | HTTP method is part of the HMAC | `test_an_upload_signature_cannot_be_replayed_as_a_download` |
| Local backend resists traversal | Resolved paths must stay under the root | `test_path_traversal_is_blocked` |
| Local backend uses constant-time comparison | `hmac.compare_digest` | — |

### Explicit non-guarantees

1. **A signed playback URL is a bearer credential.** It carries no identity;
   anyone holding it can read the object until it expires. That is why the TTL is
   5 minutes and a fresh ticket is issued per view rather than cached. It is also
   why authorisation happens *before* the URL is minted.

2. **`controlsList="nodownload"` is a hint, not protection.** The signed URL is
   visible in devtools. Real protection needs DRM (Widevine/FairPlay), which
   remains deliberately out of scope — see architecture.md §7.

3. **The local backend is not a security boundary.** It exists so a fresh clone
   can exercise the whole flow with no cloud credentials. `Settings` refuses it
   when `ENVIRONMENT=production`, because media on the API container's ephemeral
   disk would vanish on the next restart — silently, and only noticed when a
   student reported a dead video.

---

## 4. Storage abstraction

`StorageProvider` is a five-method protocol. Two implementations:

| Provider | Used for |
| --- | --- |
| `S3StorageProvider` | Cloudflare R2 in production, MinIO locally, `moto` in tests. R2 speaks the S3 API, so one client covers all three. |
| `LocalStorageProvider` | Development with no credentials. Issues HMAC-signed URLs back to the API's own routes, so the **client code path is identical** — the browser still PUTs to whatever URL it is given. |

Two botocore settings are load-bearing and easy to get wrong:

- `signature_version="s3v4"` — R2 supports only SigV4.
- `addressing_style="path"` — virtual-host style produces URLs pointing at a
  subdomain that does not resolve for MinIO or R2's account-scoped endpoint.

Both are exercised by real PUT/GET traffic in the test suite rather than asserted
on as strings.

---

## 5. Testing approach

The S3 tests run against a **real in-process S3 server** (`moto`), so a URL that
boto3 generates but a server rejects — the usual outcome of a signing or
addressing mistake — fails in CI rather than in production.

> **One honest limitation.** `moto` does not verify presigned signatures: it
> accepts a mismatched `Content-Type` that real S3 and R2 reject with `403`. The
> content-type binding is therefore asserted on the URL's *structure*, and the
> test says so explicitly. End-to-end rejection needs a MinIO or real-R2
> integration environment — recorded as debt below.

| Suite | Count |
| --- | --- |
| `tests/integration/test_media.py` | 29 |
| `web/tests/media-upload.test.ts` | 20 |
| **Feature 3 total** | **49** |
| **Project total** | **280** (149 backend, 131 web) |

---

## 6. What changes when HLS transcoding lands

Written down now, while the reasoning is fresh:

1. **A worker** (ARQ, per architecture.md §9) consumes a `transcode` queue,
   triggered on confirmation of a `lesson_video` asset.
2. **`media_assets` gains** a `processing` status and a `variants` relation (or a
   JSONB ladder description) — the current `pending → ready → failed` lifecycle
   extends rather than changes.
3. **Playback returns a manifest URL.** `PlaybackTicket` already being an object
   is what makes this a non-breaking change for the client.
4. **Per-object signed URLs stop working.** A stream is hundreds of segments, and
   signing each is impractical. The replacement is CDN **signed cookies** scoped
   to a path prefix — one credential covering the whole stream.
5. **The player swaps `<video src>` for `hls.js`**, behind the same component
   boundary.

---

## 7. Known technical debt

| Item | Impact | Trigger |
| --- | --- | --- |
| **No orphan cleanup job** | Abandoned `pending` assets and their partial objects accumulate and are billed for. `MediaRepository.list_abandoned` exists; nothing calls it. | **With the first background worker** |
| No resumable upload | A dropped connection restarts a multi-gigabyte upload from zero | First author complaint about large files |
| Presigned signature enforcement untested end-to-end | moto is lenient where R2 is strict | Add a MinIO service to CI |
| No virus scanning | Uploaded PDFs are served to students unscanned | Before accepting uploads from anyone but staff |
| No image resizing | A 10 MB cover is served at full size to every catalogue card | Once covers are actually in use |
| `openapi-typescript` still not adopted | Three features now hand-mirror schemas | **Overdue** |
| Lesson/module hard delete | Still unresolved from Feature 2; will orphan progress rows | **Before progress tracking** |

---

## 8. Operating it

**Development** — nothing to configure. `STORAGE_BACKEND=local` is the default
and needs no credentials; uploads land in a named Docker volume.

**Production** — Cloudflare R2:

```bash
STORAGE_BACKEND=s3
S3_BUCKET=med-lms-media
S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_REGION=auto
```

The bucket must **not** be public: every read goes through a signed URL. CORS on
the bucket must allow `PUT` from the web origin, or browser uploads fail the
preflight.

`Settings` refuses `STORAGE_BACKEND=local` when `ENVIRONMENT=production`, so a
misconfigured deploy fails at boot rather than silently losing uploads.
