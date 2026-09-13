// Direct object manipulation. Camera and scenery never participate in this state.
export const MAX_SHOVEL_PITCH = Math.PI / 18; // Ten degrees each way.
export class ShovelRotation {
  yaw = 0;
  pitch = 0;
  oriented = false;
  private pointer?: {
    id: number;
    x: number;
    y: number;
    span: number;
    yaw: number;
    pitch: number;
    dragged: boolean;
  };

  get held() {
    return !!this.pointer;
  }

  begin(id: number, x: number, y: number, span: number) {
    if (this.pointer) return false;
    this.pointer = {
      id,
      x,
      y,
      span: Math.max(1, span),
      yaw: this.yaw,
      pitch: this.pitch,
      dragged: false,
    };
    return true;
  }

  move(id: number, x: number, y: number) {
    const pointer = this.pointer;
    if (!pointer || pointer.id !== id) return false;
    const dx = x - pointer.x,
      dy = y - pointer.y;
    pointer.dragged ||= Math.hypot(dx, dy) >= 6;
    if (!pointer.dragged) return false;
    this.yaw = pointer.yaw + (dx / pointer.span) * Math.PI * 2;
    this.pitch = this.clampPitch(
      pointer.pitch + (dy / pointer.span) * MAX_SHOVEL_PITCH * 2,
    );
    this.oriented = true;
    return true;
  }

  end(id: number) {
    if (!this.pointer || this.pointer.id !== id) return false;
    const tapped = !this.pointer.dragged;
    this.pointer = undefined;
    return tapped;
  }

  cancel(id: number) {
    if (this.pointer?.id === id) this.pointer = undefined;
  }

  key(key: string) {
    if (key === "Home") {
      this.yaw = this.pitch = 0;
      this.oriented = false;
      this.pointer = undefined;
      return true;
    }
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(key))
      return false;
    this.yaw += key === "ArrowLeft" ? -0.16 : key === "ArrowRight" ? 0.16 : 0;
    this.pitch = this.clampPitch(
      this.pitch +
        ((key === "ArrowUp" ? -1 : key === "ArrowDown" ? 1 : 0) * Math.PI) / 90,
    );
    this.oriented = true;
    return true;
  }

  private clampPitch(pitch: number) {
    return Math.max(-MAX_SHOVEL_PITCH, Math.min(MAX_SHOVEL_PITCH, pitch));
  }
}
