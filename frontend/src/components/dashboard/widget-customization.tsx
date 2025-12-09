"use client"

import { useWidgetStore } from "@/store/widget-store"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Trash2, Copy, Share2 } from "lucide-react"

export function WidgetCustomization() {
    const { widgets, selectedWidgetId, updateWidget, removeWidget } = useWidgetStore()
    const widget = widgets.find(w => w.id === selectedWidgetId)

    if (!widget) return (
        <div className="p-6 text-center text-muted-foreground">
            Select a widget to customize
        </div>
    )

    return (
        <div className="h-full flex flex-col">
            <div className="p-4 border-b">
                <h2 className="font-semibold text-lg">Properties</h2>
            </div>

            <div className="flex-1 overflow-auto p-4 space-y-6">
                <div className="space-y-2">
                    <Label>Title</Label>
                    <Input
                        value={widget.title}
                        onChange={(e) => updateWidget(widget.id, { title: e.target.value })}
                    />
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                        <Label>Width</Label>
                        <Input
                            type="number"
                            value={widget.size.width}
                            onChange={(e) => updateWidget(widget.id, { size: { ...widget.size, width: parseInt(e.target.value) } })}
                        />
                    </div>
                    <div className="space-y-2">
                        <Label>Height</Label>
                        <Input
                            type="number"
                            value={widget.size.height}
                            onChange={(e) => updateWidget(widget.id, { size: { ...widget.size, height: parseInt(e.target.value) } })}
                        />
                    </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                        <Label>X Position</Label>
                        <Input
                            type="number"
                            value={Math.round(widget.position.x)}
                            onChange={(e) => updateWidget(widget.id, { position: { ...widget.position, x: parseInt(e.target.value) } })}
                        />
                    </div>
                    <div className="space-y-2">
                        <Label>Y Position</Label>
                        <Input
                            type="number"
                            value={Math.round(widget.position.y)}
                            onChange={(e) => updateWidget(widget.id, { position: { ...widget.position, y: parseInt(e.target.value) } })}
                        />
                    </div>
                </div>

                <Separator />

                <Tabs defaultValue="style">
                    <TabsList className="w-full">
                        <TabsTrigger value="style" className="flex-1">Style</TabsTrigger>
                        <TabsTrigger value="data" className="flex-1">Data</TabsTrigger>
                    </TabsList>
                    <TabsContent value="style" className="space-y-4 mt-4">
                        <div className="space-y-2">
                            <Label>Background</Label>
                            <div className="grid grid-cols-5 gap-2">
                                {['bg-card', 'bg-blue-500/10', 'bg-green-500/10', 'bg-purple-500/10', 'bg-orange-500/10'].map(bg => (
                                    <div key={bg} className={`h-8 rounded cursor-pointer border ${bg}`} />
                                ))}
                            </div>
                        </div>
                    </TabsContent>
                    <TabsContent value="data" className="space-y-4 mt-4">
                        <div className="space-y-2">
                            <Label>Mock Value</Label>
                            <Input
                                value={widget.data.value || ''}
                                onChange={(e) => updateWidget(widget.id, { data: { ...widget.data, value: e.target.value } })}
                                placeholder="e.g. $1,234"
                            />
                        </div>
                    </TabsContent>
                </Tabs>

                <Separator />

                <div className="space-y-2">
                    <Label>Actions</Label>
                    <div className="flex gap-2">
                        <Button variant="outline" size="sm" className="flex-1">
                            <Copy className="w-4 h-4 mr-2" /> Duplicate
                        </Button>
                        <Button variant="outline" size="sm" className="flex-1">
                            <Share2 className="w-4 h-4 mr-2" /> Export
                        </Button>
                    </div>
                    <Button
                        variant="destructive"
                        className="w-full"
                        onClick={() => removeWidget(widget.id)}
                    >
                        <Trash2 className="w-4 h-4 mr-2" /> Delete Widget
                    </Button>
                </div>
            </div>
        </div>
    )
}
