"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import * as React from "react";
import { useForm } from "react-hook-form";

import { SelectField } from "@/components/common/select-field";
import { TextField } from "@/components/common/text-field";
import { TextareaField } from "@/components/common/textarea-field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  courseFormSchema,
  type CourseFormInput,
} from "@/features/courses/schemas";
import {
  useCreateCourse,
  useUpdateCourse,
} from "@/features/courses/hooks/use-admin-courses";
import { DIFFICULTY_LABELS, type CourseDetail } from "@/features/courses/types";
import { toFormErrors } from "@/lib/api/errors";

const DIFFICULTY_OPTIONS = Object.entries(DIFFICULTY_LABELS).map(([value, label]) => ({
  value,
  label,
}));

export interface CourseFormProps {
  /** Absent when creating. */
  course?: CourseDetail;
}

/**
 * Create or edit a course.
 *
 * One component for both modes rather than two near-identical forms: the fields,
 * validation, and error mapping are the same, and the only real differences are
 * the mutation and whether the slug is editable.
 */
export function CourseForm({ course }: CourseFormProps) {
  const router = useRouter();
  const isEditing = course !== undefined;
  const [formError, setFormError] = React.useState<string | null>(null);

  const createCourse = useCreateCourse();
  const updateCourse = useUpdateCourse(course?.id ?? "");

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<CourseFormInput>({
    resolver: zodResolver(courseFormSchema),
    defaultValues: {
      title: course?.title ?? "",
      slug: course?.slug ?? undefined,
      subtitle: course?.subtitle ?? undefined,
      description: course?.description ?? undefined,
      specialty: course?.specialty ?? undefined,
      difficulty: course?.difficulty ?? "foundation",
    },
  });

  // A published course's slug is immutable server-side; disabling the input
  // makes that visible instead of letting an author discover it via a 409.
  const slugLocked = isEditing && course.status === "published";

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);

    // The slug field is disabled when locked, so it must not be submitted at all.
    const payload: CourseFormInput = slugLocked
      ? { ...values, slug: undefined }
      : values;

    try {
      if (isEditing) {
        await updateCourse.mutateAsync(payload);
        router.refresh();
      } else {
        const created = await createCourse.mutateAsync(payload);
        router.push(`/admin/courses/${created.id}`);
      }
    } catch (error) {
      // Field-level messages are mapped back onto their inputs; anything else
      // becomes a form-level banner.
      const fieldErrors = toFormErrors(error);
      const entries = Object.entries(fieldErrors);

      if (entries.length > 0) {
        for (const [field, message] of entries) {
          setError(field as keyof CourseFormInput, { type: "server", message });
        }
        return;
      }
      setFormError(
        error instanceof Error ? error.message : "Something went wrong. Please try again.",
      );
    }
  });

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      {formError !== null ? <Alert variant="destructive">{formError}</Alert> : null}

      <TextField
        label="Title"
        name="title"
        placeholder="Clinical Cardiology"
        disabled={isSubmitting}
        error={errors.title?.message}
        registration={register("title")}
        autoFocus={!isEditing}
      />

      <TextField
        label="URL slug"
        name="slug"
        placeholder="Leave blank to generate from the title"
        disabled={isSubmitting || slugLocked}
        error={errors.slug?.message}
        hint={
          slugLocked
            ? "Locked: changing a published course's URL would break existing links."
            : "Lowercase letters, numbers and hyphens."
        }
        registration={register("slug")}
      />

      <TextField
        label="Subtitle"
        name="subtitle"
        placeholder="A one-line summary shown in the catalogue"
        disabled={isSubmitting}
        error={errors.subtitle?.message}
        registration={register("subtitle")}
      />

      <div className="grid gap-5 sm:grid-cols-2">
        <TextField
          label="Specialty"
          name="specialty"
          placeholder="Cardiology"
          disabled={isSubmitting}
          error={errors.specialty?.message}
          registration={register("specialty")}
        />

        <SelectField
          label="Difficulty"
          name="difficulty"
          options={DIFFICULTY_OPTIONS}
          disabled={isSubmitting}
          error={errors.difficulty?.message}
          registration={register("difficulty")}
        />
      </div>

      <TextareaField
        label="Description"
        name="description"
        rows={6}
        placeholder="What students will learn, and who this course is for."
        disabled={isSubmitting}
        error={errors.description?.message}
        registration={register("description")}
      />

      <div className="flex gap-3">
        <Button type="submit" loading={isSubmitting}>
          {isSubmitting
            ? "Saving…"
            : isEditing
              ? "Save changes"
              : "Create course"}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={isSubmitting}
          onClick={() => router.push("/admin/courses")}
        >
          Cancel
        </Button>
      </div>

      {!isEditing ? (
        <p className="text-sm text-muted-foreground">
          The course is created as a draft. Add lessons before publishing it.
        </p>
      ) : null}
    </form>
  );
}
