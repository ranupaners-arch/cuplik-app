import { AnnotationPage } from "@/components/annotation";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AnnotationPage id={id} />;
}
