import { layout, type LayoutInput } from './layout'

/* The layout, off the main thread: a few hundred milliseconds on a large codebase
   is a frozen page if it runs where the page does.

   Typed through the DOM's `postMessage(message, { transfer })`, which a worker's
   matches, rather than by pulling the webworker lib into a program that already
   has the DOM's: the two declare the same globals and collide. */
self.onmessage = (e: MessageEvent<LayoutInput>) => {
  const result = layout(e.data)
  self.postMessage(result, {
    transfer: [result.positions.buffer, result.centres.buffer, result.radii.buffer],
  })
}
