"use client";

import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";
import * as React from "react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  useCreateLesson,
  useCreateModule,
  useDeleteLesson,
  useDeleteModule,
  useReorderLessons,
  useReorderModules,
} from "@/features/courses/hooks/use-admin-courses";
import { minutesToSeconds } from "@/features/courses/schemas";
import { LessonVideoUploader } from "@/features/media/components/lesson-video-uploader";
import {
  CONTENT_TYPE_LABELS,
  formatDuration,
  type CourseDetail,
  type CourseModule,
  type LessonContentType,
} from "@/features/courses/types";

const CONTENT_TYPES = Object.keys(CONTENT_TYPE_LABELS) as LessonContentType[];

/**
 * Move an item within a list, returning a new array.
 *
 * Returns the original when the move is out of bounds, so callers do not have to
 * guard the first and last positions.
 */
function moved<T>(items: readonly T[], from: number, to: number): T[] {
  if (to < 0 || to >= items.length) {
    return [...items];
  }
  const next = [...items];
  const [item] = next.splice(from, 1);
  if (item === undefined) {
    return [...items];
  }
  next.splice(to, 0, item);
  return next;
}

export interface CourseOutlineEditorProps {
  course: CourseDetail;
}

/**
 * Author a course's modules and lessons.
 *
 * **Reordering uses up/down buttons, not drag-and-drop.** A drag implementation
 * would need `dnd-kit` (~30 kB) plus a keyboard-accessible fallback, since drag
 * alone is unusable with a keyboard or screen reader — so the accessible controls
 * have to exist either way. Buttons alone are keyboard-operable by default,
 * announce their action, and work on touch without conflicting with scroll. When
 * courses routinely exceed ~20 modules, revisit and add drag *on top of* these.
 *
 * Each reorder sends the complete new order, matching the API's whole-set
 * replacement contract.
 */
export function CourseOutlineEditor({ course }: CourseOutlineEditorProps) {
  const [error, setError] = React.useState<string | null>(null);

  const createModule = useCreateModule(course.id);
  const deleteModule = useDeleteModule(course.id);
  const reorderModules = useReorderModules(course.id);

  const modules = course.modules;

  const handleModuleMove = async (index: number, direction: -1 | 1) => {
    const ordered = moved(modules, index, index + direction);
    setError(null);
    try {
      await reorderModules.mutateAsync(ordered.map((module) => module.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reorder modules.");
    }
  };

  const handleModuleDelete = async (module: CourseModule) => {
    const lessonCount = module.lessons.length;
    const confirmed = window.confirm(
      lessonCount > 0
        ? `Delete "${module.title}" and its ${lessonCount} lesson(s)? This cannot be undone.`
        : `Delete "${module.title}"?`,
    );
    if (!confirmed) {
      return;
    }
    setError(null);
    try {
      await deleteModule.mutateAsync(module.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete the module.");
    }
  };

  return (
    <div className="space-y-4">
      {error !== null ? <Alert variant="destructive">{error}</Alert> : null}

      {modules.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            No modules yet. Add one below to start building this course.
          </CardContent>
        </Card>
      ) : (
        <ol className="space-y-4">
          {modules.map((module, index) => (
            <li key={module.id}>
              <ModuleEditor
                courseId={course.id}
                module={module}
                index={index}
                isFirst={index === 0}
                isLast={index === modules.length - 1}
                isBusy={reorderModules.isPending || deleteModule.isPending}
                onMoveUp={() => void handleModuleMove(index, -1)}
                onMoveDown={() => void handleModuleMove(index, 1)}
                onDelete={() => void handleModuleDelete(module)}
              />
            </li>
          ))}
        </ol>
      )}

      <AddModuleForm
        isPending={createModule.isPending}
        onSubmit={async (title) => {
          setError(null);
          try {
            await createModule.mutateAsync({ title });
            return true;
          } catch (cause) {
            setError(cause instanceof Error ? cause.message : "Could not add the module.");
            return false;
          }
        }}
      />
    </div>
  );
}

// ── Module ───────────────────────────────────────────────────────────────────

interface ModuleEditorProps {
  courseId: string;
  module: CourseModule;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  isBusy: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDelete: () => void;
}

function ModuleEditor({
  courseId,
  module,
  index,
  isFirst,
  isLast,
  isBusy,
  onMoveUp,
  onMoveDown,
  onDelete,
}: ModuleEditorProps) {
  const [error, setError] = React.useState<string | null>(null);

  const createLesson = useCreateLesson(courseId);
  const deleteLesson = useDeleteLesson(courseId);
  const reorderLessons = useReorderLessons(courseId);

  const handleLessonMove = async (lessonIndex: number, direction: -1 | 1) => {
    const ordered = moved(module.lessons, lessonIndex, lessonIndex + direction);
    setError(null);
    try {
      await reorderLessons.mutateAsync({
        moduleId: module.id,
        orderedIds: ordered.map((lesson) => lesson.id),
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reorder lessons.");
    }
  };

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0 pb-3">
        <div className="flex items-baseline gap-3">
          <span className="text-sm font-medium text-muted-foreground">
            {String(index + 1).padStart(2, "0")}
          </span>
          <div>
            <h3 className="font-semibold">{module.title}</h3>
            <p className="text-sm text-muted-foreground">
              {module.lessons.length}{" "}
              {module.lessons.length === 1 ? "lesson" : "lessons"}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={isFirst || isBusy}
            onClick={onMoveUp}
            aria-label={`Move ${module.title} up`}
          >
            <ChevronUp className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={isLast || isBusy}
            onClick={onMoveDown}
            aria-label={`Move ${module.title} down`}
          >
            <ChevronDown className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={isBusy}
            onClick={onDelete}
            aria-label={`Delete ${module.title}`}
            className="text-destructive hover:text-destructive"
          >
            <Trash2 className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {error !== null ? <Alert variant="destructive">{error}</Alert> : null}

        {module.lessons.length > 0 ? (
          <ol className="divide-y divide-border">
            {module.lessons.map((lesson, lessonIndex) => (
              <li key={lesson.id} className="space-y-2 py-2">
                <div className="flex items-center gap-3 text-sm">
                <span className="flex-1 font-medium">{lesson.title}</span>
                <Badge variant="neutral">
                  {CONTENT_TYPE_LABELS[lesson.content_type]}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {formatDuration(lesson.duration_seconds)}
                </span>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    disabled={lessonIndex === 0 || reorderLessons.isPending}
                    onClick={() => void handleLessonMove(lessonIndex, -1)}
                    aria-label={`Move ${lesson.title} up`}
                  >
                    <ChevronUp className="h-4 w-4" aria-hidden="true" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    disabled={
                      lessonIndex === module.lessons.length - 1 ||
                      reorderLessons.isPending
                    }
                    onClick={() => void handleLessonMove(lessonIndex, 1)}
                    aria-label={`Move ${lesson.title} down`}
                  >
                    <ChevronDown className="h-4 w-4" aria-hidden="true" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    disabled={deleteLesson.isPending}
                    onClick={() => {
                      if (window.confirm(`Delete "${lesson.title}"?`)) {
                        void deleteLesson.mutateAsync(lesson.id);
                      }
                    }}
                    aria-label={`Delete ${lesson.title}`}
                    className="text-destructive hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </Button>
                  </div>
                </div>
                {lesson.content_type === "video" ? (
                  <LessonVideoUploader courseId={courseId} lesson={lesson} />
                ) : null}
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-muted-foreground">No lessons in this module yet.</p>
        )}

        <AddLessonForm
          moduleId={module.id}
          isPending={createLesson.isPending}
          onSubmit={async (moduleId, input) => {
            setError(null);
            try {
              await createLesson.mutateAsync({ moduleId, input });
              return true;
            } catch (cause) {
              setError(
                cause instanceof Error ? cause.message : "Could not add the lesson.",
              );
              return false;
            }
          }}
        />
      </CardContent>
    </Card>
  );
}

// ── Inline creation forms ────────────────────────────────────────────────────

interface AddModuleFormProps {
  isPending: boolean;
  onSubmit: (title: string) => Promise<boolean>;
}

function AddModuleForm({ isPending, onSubmit }: AddModuleFormProps) {
  const [title, setTitle] = React.useState("");

  return (
    <form
      className="flex gap-2"
      onSubmit={async (event) => {
        event.preventDefault();
        if (title.trim().length === 0) {
          return;
        }
        // Only clear on success, so a failed submit does not lose the input.
        if (await onSubmit(title.trim())) {
          setTitle("");
        }
      }}
    >
      <div className="flex-1">
        <Label htmlFor="new-module-title" className="sr-only">
          New module title
        </Label>
        <Input
          id="new-module-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="New module title"
          disabled={isPending}
          maxLength={200}
        />
      </div>
      <Button type="submit" loading={isPending} disabled={title.trim().length === 0}>
        <Plus className="h-4 w-4" aria-hidden="true" />
        Add module
      </Button>
    </form>
  );
}

interface AddLessonFormProps {
  moduleId: string;
  isPending: boolean;
  onSubmit: (
    moduleId: string,
    input: {
      title: string;
      content_type: LessonContentType;
      duration_seconds?: number;
      is_free_preview: boolean;
    },
  ) => Promise<boolean>;
}

function AddLessonForm({ moduleId, isPending, onSubmit }: AddLessonFormProps) {
  const [title, setTitle] = React.useState("");
  const [contentType, setContentType] = React.useState<LessonContentType>("video");
  const [minutes, setMinutes] = React.useState("");

  return (
    <form
      className="flex flex-wrap items-end gap-2 border-t border-border pt-3"
      onSubmit={async (event) => {
        event.preventDefault();
        if (title.trim().length === 0) {
          return;
        }
        const parsedMinutes = minutes === "" ? undefined : Number(minutes);
        const seconds = minutesToSeconds(parsedMinutes);

        const succeeded = await onSubmit(moduleId, {
          title: title.trim(),
          content_type: contentType,
          ...(seconds !== undefined ? { duration_seconds: seconds } : {}),
          is_free_preview: false,
        });
        if (succeeded) {
          setTitle("");
          setMinutes("");
        }
      }}
    >
      <div className="min-w-[200px] flex-1">
        <Label htmlFor={`lesson-title-${moduleId}`} className="sr-only">
          New lesson title
        </Label>
        <Input
          id={`lesson-title-${moduleId}`}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="New lesson title"
          disabled={isPending}
          maxLength={200}
        />
      </div>

      <div className="w-32">
        <Label htmlFor={`lesson-type-${moduleId}`} className="sr-only">
          Lesson type
        </Label>
        <Select
          id={`lesson-type-${moduleId}`}
          value={contentType}
          onChange={(event) => setContentType(event.target.value as LessonContentType)}
          disabled={isPending}
        >
          {CONTENT_TYPES.map((type) => (
            <option key={type} value={type}>
              {CONTENT_TYPE_LABELS[type]}
            </option>
          ))}
        </Select>
      </div>

      <div className="w-28">
        <Label htmlFor={`lesson-minutes-${moduleId}`} className="sr-only">
          Duration in minutes
        </Label>
        <Input
          id={`lesson-minutes-${moduleId}`}
          type="number"
          min={1}
          max={1440}
          value={minutes}
          onChange={(event) => setMinutes(event.target.value)}
          placeholder="Minutes"
          disabled={isPending}
        />
      </div>

      <Button
        type="submit"
        variant="outline"
        loading={isPending}
        disabled={title.trim().length === 0}
      >
        <Plus className="h-4 w-4" aria-hidden="true" />
        Add lesson
      </Button>
    </form>
  );
}
