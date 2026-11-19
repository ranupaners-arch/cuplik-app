import { OutputPage } from "@/components/output";
export default async function Page({ params }: { params: Promise<{ id: string }> }) { const { id } = await params; return <OutputPage id={id} />; }
